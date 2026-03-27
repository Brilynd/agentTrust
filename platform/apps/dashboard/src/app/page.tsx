"use client";

import { useEffect, useMemo, useState, type ChangeEvent, type Dispatch, type SetStateAction } from "react";

import { deleteJson, getJson, postJson, putJson } from "../lib/api";
import { socket } from "../lib/socket";
import { useAgentsStore } from "../store/useAgentsStore";

type StepRecord = {
  id: string;
  sequence: number;
  name: string;
  status: string;
  retryCount: number;
  failureType: string;
  failureMessage?: string | null;
  createdAt: string;
};

type OperatorPromptRecord = {
  prompt: string;
  details?: Record<string, unknown>;
  createdAt: string;
};

type SensitiveGrantRecord = {
  id?: string;
  referenceKey?: string;
  label?: string;
  category?: string;
  fieldNames?: string[];
};

type JobRecord = {
  id: string;
  status: string;
  progress: number;
  currentStep?: string | null;
  error?: string | null;
  metadata?: {
    operatorPrompts?: OperatorPromptRecord[];
    sensitiveDataGrants?: SensitiveGrantRecord[];
  } | null;
  steps?: StepRecord[];
};

type JobsResponse = {
  jobs: JobRecord[];
};

type ApprovalsResponse = {
  approvals: Array<{
    id: string;
    action: string;
    policyReason?: string | null;
    jobId: string;
  }>;
};

type MetricsResponse = {
  metrics: {
    successRate: number;
    totalJobs: number;
    completedJobs: number;
    failedJobs: number;
    waitingApproval: number;
    averageRetries: number;
    averageExecutionMs: number;
    failureBreakdown: Record<string, number>;
  };
};

type ReplayResponse = {
  replay: Array<{
    id: string;
    sequence: number;
    eventType: string;
    payload: Record<string, unknown>;
  }>;
};

type ResetHistoryResponse = {
  cleared: {
    deletedJobs: number;
    deletedApprovals: number;
    deletedWorkers: number;
    deletedActions: number;
    preservedStatuses: string[];
  };
};

type ConfigurationRecord = {
  id: string;
  name: string;
  description?: string;
  task: string;
  details: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

type ConfigurationDraftResponse = {
  draft: {
    name: string;
    description: string;
    task: string;
    allowedDomains: string[];
    startUrl: string;
    verifyText: string;
    highRiskKeywords: string[];
    auditorKeywords: string[];
    advancedJson: Record<string, unknown>;
  };
};

type UserRecord = {
  id: string;
  email: string;
  name?: string | null;
};

type UserAuthResponse = {
  success: boolean;
  user: UserRecord;
  token: string;
};

type SensitiveRecord = {
  id: string;
  referenceKey: string;
  label?: string | null;
  category?: string | null;
  fieldNames: string[];
  allowedDomains: string[];
  tags: string[];
  createdAt: string;
  updatedAt: string;
};

type SensitiveRecordsResponse = {
  records: SensitiveRecord[];
};

type SensitiveCreateResponse = {
  success: boolean;
  record: SensitiveRecord & {
    fieldRefs: Record<string, string>;
  };
};

function replaySummary(payload: Record<string, unknown>) {
  const progressLine =
    typeof payload.line === "string"
      ? (payload.line.split("|", 2)[1] || payload.line).trim()
      : "";
  return [
    progressLine,
    typeof payload.goal === "string" ? payload.goal : "",
    typeof payload.message === "string" ? payload.message : "",
    typeof payload.observation === "string" ? payload.observation : "",
    typeof payload.error === "string" ? payload.error : ""
  ]
    .filter(Boolean)
    .join(" | ");
}

function replayTitle(eventType: string, payload: Record<string, unknown>) {
  if (eventType === "progress.line" && typeof payload.line === "string") {
    const [phase, detail] = payload.line.split("|", 2);
    if (detail?.trim()) {
      return detail.trim();
    }
    if (phase?.trim()) {
      return `${formatStatusLabel(phase).replace(/\b\w/g, (char) => char.toUpperCase())} update`;
    }
    return "Progress update";
  }

  if (eventType.startsWith("action.")) {
    const [, actionType, outcome] = eventType.split(".");
    const actionLabel = formatStatusLabel(actionType || "action");
    const outcomeLabel = formatStatusLabel(outcome || "");
    return `${actionLabel.replace(/\b\w/g, (char) => char.toUpperCase())}${outcomeLabel ? ` · ${outcomeLabel}` : ""}`;
  }

  return eventType;
}

function replayActionType(payload: Record<string, unknown>) {
  return typeof payload.actionType === "string" ? payload.actionType : "";
}

function isMutatingReplayEvent(entry: ReplayResponse["replay"][number]) {
  if (!entry.eventType.startsWith("action.")) {
    return false;
  }
  const actionType = replayActionType(entry.payload);
  return [
    "navigation",
    "click",
    "form_submit",
    "type_text",
    "form_input",
    "press_key",
    "select_option",
    "dismiss_overlays",
  ].includes(actionType);
}

function replayAuditCards(replayEvents: ReplayResponse["replay"]) {
  return replayEvents
    .filter((entry) => isMutatingReplayEvent(entry) && typeof entry.payload.screenshotBase64 === "string")
    .slice()
    .reverse()
    .slice(0, 12);
}

function replayBackgroundEvents(replayEvents: ReplayResponse["replay"]) {
  return replayEvents
    .filter((entry) => !isMutatingReplayEvent(entry) || typeof entry.payload.screenshotBase64 !== "string")
    .slice()
    .reverse()
    .slice(0, 20);
}

function formatStatusLabel(status: string) {
  return status.replace(/_/g, " ");
}

function statusTone(status: string) {
  switch (status) {
    case "running":
      return "running";
    case "succeeded":
    case "completed":
      return "completed";
    case "failed":
    case "cancelled":
      return "failed";
    case "waiting_approval":
      return "waiting";
    case "paused":
      return "paused";
    default:
      return "queued";
  }
}

function stepMarkerText(step: StepRecord) {
  switch (step.status) {
    case "succeeded":
    case "completed":
      return "OK";
    case "failed":
    case "cancelled":
      return "!";
    case "running":
      return "...";
    case "waiting_approval":
      return "?";
    case "paused":
      return "||";
    default:
      return String(step.sequence + 1);
  }
}

function stepOutcomeSummary(step: StepRecord) {
  if (step.status === "succeeded" || step.status === "completed") {
    return "Goal completed.";
  }
  if (step.status === "running") {
    return "Goal is currently in progress.";
  }
  if (step.status === "waiting_approval") {
    return "Waiting for approval before continuing.";
  }
  if (step.status === "paused") {
    return "Goal is paused.";
  }
  if (step.status === "failed" || step.status === "cancelled") {
    return step.failureType && step.failureType !== "NONE"
      ? `Goal did not complete because of ${formatStatusLabel(step.failureType).toLowerCase()}.`
      : "Goal did not complete.";
  }
  return "Goal is queued.";
}

function stepFailureDetail(step: StepRecord, jobError?: string | null) {
  const message = String(step.failureMessage || "").trim();
  if (
    message &&
    message !== "Goal was not completed by the LangGraph worker run"
  ) {
    return message;
  }
  return String(jobError || message || "").trim();
}

function replayStepSequence(payload: Record<string, unknown>) {
  return typeof payload.stepSequence === "number" ? payload.stepSequence : null;
}

function stepGeneratedActions(
  step: StepRecord,
  replayEvents: ReplayResponse["replay"]
) {
  const labels = replayEvents
    .filter((entry) => replayStepSequence(entry.payload) === step.sequence)
    .map((entry) => {
      if (entry.eventType.startsWith("action.")) {
        return replayTitle(entry.eventType, entry.payload);
      }
      if (entry.eventType === "progress.line" && typeof entry.payload.line === "string") {
        const [phase, detail] = entry.payload.line.split("|", 2);
        if (phase === "ACT" && detail?.trim()) {
          return detail.trim();
        }
        if (phase === "AUDIT" && detail?.trim()) {
          return `Audit: ${detail.trim()}`;
        }
        if (phase === "VERIFY" && detail?.trim()) {
          return `Verify: ${detail.trim()}`;
        }
      }
      return "";
    })
    .filter(Boolean);

  return Array.from(new Set(labels)).slice(-6);
}

function flattenSensitiveFields(value: unknown, prefix = ""): string[] {
  if (value === null || value === undefined) {
    return prefix ? [prefix] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      flattenSensitiveFields(item, prefix ? `${prefix}.${index}` : String(index))
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return prefix ? [prefix] : [];
    }
    return entries.flatMap(([key, child]) =>
      flattenSensitiveFields(child, prefix ? `${prefix}.${key}` : key)
    );
  }

  return prefix ? [prefix] : [];
}

function normalizeSensitiveGrants(records: SensitiveRecord[], selectedIds: string[]): SensitiveGrantRecord[] {
  const selected = new Set(selectedIds);
  return records
    .filter((record) => selected.has(record.id))
    .map((record) => ({
      id: record.id,
      referenceKey: record.referenceKey,
      label: record.label || record.referenceKey,
      category: record.category || "pii",
      fieldNames: record.fieldNames
    }));
}

const SENSITIVE_TOKEN_KEY = "agenttrust.dashboard.userToken";

export default function DashboardPage() {
  const { jobs, approvals, selectedJobId, setJobs, upsertJob, setApprovals, setSelectedJobId } = useAgentsStore();
  const [selectedJob, setSelectedJob] = useState<JobRecord | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse["metrics"] | null>(null);
  const [replayCount, setReplayCount] = useState(0);
  const [replayEvents, setReplayEvents] = useState<ReplayResponse["replay"]>([]);
  const [activeTab, setActiveTab] = useState<"monitor" | "jobs" | "approvals" | "metrics" | "configurations" | "sensitive">("monitor");
  const [launchConfigId, setLaunchConfigId] = useState("");
  const [launchTaskOverride, setLaunchTaskOverride] = useState("");
  const [launchRuntimeNotes, setLaunchRuntimeNotes] = useState("");
  const [launchSensitiveRecordIds, setLaunchSensitiveRecordIds] = useState<string[]>([]);
  const [launchError, setLaunchError] = useState("");
  const [launchSuccess, setLaunchSuccess] = useState("");
  const [contextPrompt, setContextPrompt] = useState("");
  const [contextDetails, setContextDetails] = useState(`{
  "appendSteps": []
}`);
  const [contextSensitiveRecordIds, setContextSensitiveRecordIds] = useState<string[]>([]);
  const [contextError, setContextError] = useState("");
  const [contextSuccess, setContextSuccess] = useState("");
  const [configurations, setConfigurations] = useState<ConfigurationRecord[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState<string>("");
  const [configPrompt, setConfigPrompt] = useState("");
  const [configPromptBusy, setConfigPromptBusy] = useState(false);
  const [configName, setConfigName] = useState("");
  const [configDescription, setConfigDescription] = useState("");
  const [configTask, setConfigTask] = useState("");
  const [configDomains, setConfigDomains] = useState("");
  const [configStartUrl, setConfigStartUrl] = useState("");
  const [configVerifyText, setConfigVerifyText] = useState("");
  const [configHighRiskKeywords, setConfigHighRiskKeywords] = useState("");
  const [configAuditorKeywords, setConfigAuditorKeywords] = useState("");
  const [configAdvancedJson, setConfigAdvancedJson] = useState(`{
  "metadata": {
    "notes": "Optional advanced fields"
  }
}`);
  const [configError, setConfigError] = useState("");
  const [configSuccess, setConfigSuccess] = useState("");
  const [userToken, setUserToken] = useState("");
  const [currentUser, setCurrentUser] = useState<UserRecord | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");
  const [sensitiveRecords, setSensitiveRecords] = useState<SensitiveRecord[]>([]);
  const [sensitiveLabel, setSensitiveLabel] = useState("");
  const [sensitiveReferenceKey, setSensitiveReferenceKey] = useState("");
  const [sensitiveCategory, setSensitiveCategory] = useState("pii");
  const [sensitiveAllowedDomains, setSensitiveAllowedDomains] = useState("");
  const [sensitiveTags, setSensitiveTags] = useState("");
  const [sensitiveJsonInput, setSensitiveJsonInput] = useState(`{
  "firstName": "Jane",
  "lastName": "Doe",
  "ssn": "123-45-6789"
}`);
  const [sensitiveError, setSensitiveError] = useState("");
  const [sensitiveSuccess, setSensitiveSuccess] = useState("");
  const [latestFieldRefs, setLatestFieldRefs] = useState<Record<string, string>>({});
  const [historyResetBusy, setHistoryResetBusy] = useState(false);
  const [historyResetError, setHistoryResetError] = useState("");
  const [historyResetSuccess, setHistoryResetSuccess] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const loadSelectedJob = async (jobId: string) => {
    const { job } = await getJson<{ job: JobRecord }>(`/api/jobs/${jobId}`);
    setSelectedJob(job);
    const replay = await getJson<ReplayResponse>(`/api/replays/${jobId}`);
    setReplayCount(replay.replay.length);
    setReplayEvents(replay.replay);
  };

  const loadConfigurations = async () => {
    const data = await getJson<{ configurations: ConfigurationRecord[] }>("/api/configurations");
    setConfigurations(data.configurations);
    if (!launchConfigId && data.configurations[0]?.id) {
      setLaunchConfigId(data.configurations[0].id);
    }
  };

  const loadDashboardData = async () => {
    const [jobsData, approvalsData, metricsData] = await Promise.all([
      getJson<JobsResponse>("/api/jobs"),
      getJson<ApprovalsResponse>("/api/approvals"),
      getJson<MetricsResponse>("/api/metrics/summary")
    ]);

    setJobs(jobsData.jobs);
    setApprovals(approvalsData.approvals);
    setMetrics(metricsData.metrics);
    return jobsData.jobs;
  };

  const loadSensitiveRecords = async (token: string) => {
    const data = await getJson<SensitiveRecordsResponse>("/api/sensitive-data", { token });
    setSensitiveRecords(data.records);
  };

  const parseJsonInput = (value: string) => {
    if (!value.trim()) {
      return {};
    }
    return JSON.parse(value) as Record<string, unknown>;
  };

  const parseSensitiveJsonInput = () => {
    const parsed = JSON.parse(sensitiveJsonInput) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Sensitive data JSON must be an object at the top level");
    }
    return parsed as Record<string, unknown>;
  };

  const previewReferenceKey = sensitiveReferenceKey.trim() || "your_record_key";

  const sensitivePreview = useMemo(() => {
    try {
      const parsed = JSON.parse(sensitiveJsonInput) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { error: "Sensitive data JSON must be an object at the top level", fieldPaths: [] as string[] };
      }
      return { error: "", fieldPaths: flattenSensitiveFields(parsed) };
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : "Invalid JSON",
        fieldPaths: [] as string[]
      };
    }
  }, [sensitiveJsonInput]);

  useEffect(() => {
    void Promise.all([loadDashboardData(), loadConfigurations()]);
  }, [setApprovals, setJobs]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedToken = window.localStorage.getItem(SENSITIVE_TOKEN_KEY) || "";
    if (!storedToken) return;
    setUserToken(storedToken);
  }, []);

  useEffect(() => {
    if (!userToken) {
      setCurrentUser(null);
      setSensitiveRecords([]);
      return;
    }

    void getJson<{ success: boolean; user: UserRecord }>("/api/users/me", { token: userToken })
      .then((data) => {
        setCurrentUser(data.user);
        return loadSensitiveRecords(userToken);
      })
      .catch((error) => {
        setAuthError(error instanceof Error ? error.message : "Failed to authenticate");
        setUserToken("");
        setCurrentUser(null);
        setSensitiveRecords([]);
        if (typeof window !== "undefined") {
          window.localStorage.removeItem(SENSITIVE_TOKEN_KEY);
        }
      });
  }, [userToken]);

  useEffect(() => {
    socket.on("job.created", upsertJob);
    socket.on("job.updated", async (job: JobRecord) => {
      upsertJob(job);
      if (job.id === selectedJobId) {
        await loadSelectedJob(job.id);
      }
    });
    socket.on("job.context_added", async ({ jobId }: { jobId: string }) => {
      if (jobId === selectedJobId) {
        await loadSelectedJob(jobId);
      }
    });
    socket.on("approval.created", async () => {
      const data = await getJson<ApprovalsResponse>("/api/approvals");
      setApprovals(data.approvals);
    });
    socket.on("approval.updated", async () => {
      const data = await getJson<ApprovalsResponse>("/api/approvals");
      setApprovals(data.approvals);
    });
    socket.on("dashboard.history_cleared", async () => {
      const jobsAfterRefresh = await loadDashboardData();
      if (!selectedJobId) {
        setSelectedJob(null);
        setReplayCount(0);
        setReplayEvents([]);
        return;
      }
      if (!jobsAfterRefresh.some((job) => job.id === selectedJobId)) {
        setSelectedJobId(undefined);
        setSelectedJob(null);
        setReplayCount(0);
        setReplayEvents([]);
        return;
      }
      await loadSelectedJob(selectedJobId);
    });
    socket.on("replay.updated", async ({ jobId }: { jobId: string }) => {
      if (jobId === selectedJobId) {
        const replay = await getJson<ReplayResponse>(`/api/replays/${jobId}`);
        setReplayCount(replay.replay.length);
        setReplayEvents(replay.replay);
      }
    });
    return () => {
      socket.off("job.created", upsertJob);
      socket.off("job.updated");
      socket.off("job.context_added");
      socket.off("approval.created");
      socket.off("approval.updated");
      socket.off("dashboard.history_cleared");
      socket.off("replay.updated");
    };
  }, [selectedJobId, setApprovals, upsertJob]);

  useEffect(() => {
    if (!selectedJobId) return;
    void loadSelectedJob(selectedJobId);
  }, [selectedJobId]);

  const selectedTimeline = useMemo(() => selectedJob?.steps || [], [selectedJob]);
  const operatorPrompts = useMemo(
    () => selectedJob?.metadata?.operatorPrompts || [],
    [selectedJob]
  );
  const selectedJobSensitiveGrants = useMemo(
    () => selectedJob?.metadata?.sensitiveDataGrants || [],
    [selectedJob]
  );
  useEffect(() => {
    if (!selectedJobSensitiveGrants.length) {
      setContextSensitiveRecordIds([]);
      return;
    }
    const grantedIds = selectedJobSensitiveGrants
      .map((grant) => String(grant.id || "").trim())
      .filter(Boolean);
    setContextSensitiveRecordIds(grantedIds);
  }, [selectedJobSensitiveGrants]);
  const sortedJobs = useMemo(() => {
    const rank: Record<string, number> = {
      running: 0,
      waiting_approval: 1,
      paused: 2,
      queued: 3,
      failed: 4,
      cancelled: 5,
      completed: 6
    };
    return [...jobs].sort((left, right) => {
      const statusDiff = (rank[left.status] ?? 99) - (rank[right.status] ?? 99);
      if (statusDiff !== 0) return statusDiff;
      return (right.progress || 0) - (left.progress || 0);
    });
  }, [jobs]);

  const runningJobsCount = useMemo(
    () => jobs.filter((job) => job.status === "running").length,
    [jobs]
  );
  const failedJobsCount = useMemo(
    () => jobs.filter((job) => job.status === "failed").length,
    [jobs]
  );
  const pausedJobsCount = useMemo(
    () => jobs.filter((job) => job.status === "paused").length,
    [jobs]
  );
  const waitingJobsCount = approvals.length;

  const tabMeta = {
    monitor: {
      label: "Monitoring Center",
      description: "Track live operations, approvals, screenshots, and goal completion in one control surface."
    },
    jobs: {
      label: "Process Inventory",
      description: "Review every worker-backed operation with stable ordering, replay context, and process health."
    },
    approvals: {
      label: "Approval Operations",
      description: "Resolve high-risk actions and sensitive-data reveals without losing live execution context."
    },
    metrics: {
      label: "Operational Telemetry",
      description: "Measure run health, retries, throughput, and failure patterns across the fleet."
    },
    configurations: {
      label: "Reusable Bot Profiles",
      description: "Author and launch enterprise-ready configurations without forcing operators into raw JSON."
    },
    sensitive: {
      label: "Sensitive Data Control",
      description: "Store encrypted customer data, generate vault references, and manage per-operation profile access."
    }
  } as const;

  const currentTabMeta = tabMeta[activeTab];

  const refreshDashboard = async () => {
    setHistoryResetError("");
    setHistoryResetSuccess("");
    try {
      const jobsAfterRefresh = await loadDashboardData();
      if (!selectedJobId) return;
      if (!jobsAfterRefresh.some((job) => job.id === selectedJobId)) {
        setSelectedJobId(undefined);
        setSelectedJob(null);
        setReplayCount(0);
        setReplayEvents([]);
        return;
      }
      await loadSelectedJob(selectedJobId);
    } catch (error) {
      setHistoryResetError(error instanceof Error ? error.message : "Failed to refresh dashboard state");
    }
  };

  const resetDashboardHistory = async () => {
    if (typeof window !== "undefined") {
      const confirmed = window.confirm(
        "Clear past dashboard activity? This removes historical process runs, replay history, completed approvals, worker history, and logged actions. Active jobs stay visible."
      );
      if (!confirmed) return;
    }

    setHistoryResetBusy(true);
    setHistoryResetError("");
    setHistoryResetSuccess("");

    try {
      const response = await postJson<ResetHistoryResponse>("/api/dashboard/reset-history");
      const jobsAfterRefresh = await loadDashboardData();
      if (!selectedJobId || !jobsAfterRefresh.some((job) => job.id === selectedJobId)) {
        setSelectedJobId(undefined);
        setSelectedJob(null);
        setReplayCount(0);
        setReplayEvents([]);
      } else {
        await loadSelectedJob(selectedJobId);
      }
      setHistoryResetSuccess(
        `Cleared ${response.cleared.deletedJobs} historical process runs, ${response.cleared.deletedActions} logged actions, and ${response.cleared.deletedWorkers} worker records.`
      );
    } catch (error) {
      setHistoryResetError(error instanceof Error ? error.message : "Failed to clear dashboard history");
    } finally {
      setHistoryResetBusy(false);
    }
  };

  const buildSensitiveGrantPayload = (selectedIds: string[]) =>
    normalizeSensitiveGrants(sensitiveRecords, selectedIds);

  const toggleSensitiveRecordSelection = (
    recordId: string,
    setSelectedIds: Dispatch<SetStateAction<string[]>>
  ) => {
    setSelectedIds((current) =>
      current.includes(recordId) ? current.filter((value) => value !== recordId) : [...current, recordId]
    );
  };

  const resetConfigForm = () => {
    setSelectedConfigId("");
    setConfigPrompt("");
    setConfigName("");
    setConfigDescription("");
    setConfigTask("");
    setConfigDomains("");
    setConfigStartUrl("");
    setConfigVerifyText("");
    setConfigHighRiskKeywords("");
    setConfigAuditorKeywords("");
    setConfigAdvancedJson(`{
  "metadata": {
    "notes": "Optional advanced fields"
  }
}`);
  };

  const resetSensitiveForm = () => {
    setSensitiveLabel("");
    setSensitiveReferenceKey("");
    setSensitiveCategory("pii");
    setSensitiveAllowedDomains("");
    setSensitiveTags("");
    setSensitiveJsonInput(`{
  "firstName": "Jane",
  "lastName": "Doe",
  "ssn": "123-45-6789"
}`);
    setSensitiveError("");
    setSensitiveSuccess("");
    setLatestFieldRefs({});
  };

  const copyToClipboard = async (value: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setSensitiveSuccess(successMessage);
      setSensitiveError("");
    } catch (error) {
      setSensitiveError(error instanceof Error ? error.message : "Failed to copy to clipboard");
    }
  };

  const handleSensitiveFileUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      setSensitiveJsonInput(JSON.stringify(parsed, null, 2));
      setSensitiveError("");
      setSensitiveSuccess(`Loaded ${file.name}. Review the fields, then click Save encrypted record.`);
    } catch (error) {
      setSensitiveError(error instanceof Error ? error.message : "Failed to parse uploaded JSON");
      setSensitiveSuccess("");
    } finally {
      event.target.value = "";
    }
  };

  const loginSensitiveVault = async () => {
    setAuthBusy(true);
    setAuthError("");
    setAuthSuccess("");
    try {
      if (!authEmail.trim() || !authPassword) {
        throw new Error("Enter your email and password first");
      }
      const response = await postJson<UserAuthResponse>("/api/users/login", {
        email: authEmail.trim(),
        password: authPassword
      });
      setUserToken(response.token);
      setCurrentUser(response.user);
      setAuthPassword("");
      setAuthSuccess("Signed in. Sensitive uploads will be encrypted in the backend.");
      if (typeof window !== "undefined") {
        window.localStorage.setItem(SENSITIVE_TOKEN_KEY, response.token);
      }
      await loadSensitiveRecords(response.token);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Login failed");
    } finally {
      setAuthBusy(false);
    }
  };

  const logoutSensitiveVault = () => {
    setUserToken("");
    setCurrentUser(null);
    setAuthPassword("");
    setAuthError("");
    setAuthSuccess("Signed out of sensitive data vault access.");
    setSensitiveRecords([]);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(SENSITIVE_TOKEN_KEY);
    }
  };

  const saveSensitiveRecord = async () => {
    setSensitiveError("");
    setSensitiveSuccess("");
    try {
      if (!userToken) {
        throw new Error("Sign in to save encrypted sensitive data");
      }
      const fields = parseSensitiveJsonInput();
      const response = await postJson<SensitiveCreateResponse>(
        "/api/sensitive-data",
        {
          label: sensitiveLabel.trim() || undefined,
          referenceKey: sensitiveReferenceKey.trim() || undefined,
          category: sensitiveCategory.trim() || "pii",
          allowedDomains: sensitiveAllowedDomains
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          tags: sensitiveTags
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          fields
        },
        { token: userToken }
      );
      setLatestFieldRefs(response.record.fieldRefs || {});
      setSensitiveSuccess("Sensitive record encrypted and saved. Use the generated vault references in process JSON.");
      await loadSensitiveRecords(userToken);
      setSensitiveReferenceKey(response.record.referenceKey);
      if (!sensitiveLabel.trim() && response.record.label) {
        setSensitiveLabel(response.record.label);
      }
    } catch (error) {
      setSensitiveError(error instanceof Error ? error.message : "Failed to save sensitive record");
    }
  };

  const deleteSensitiveRecord = async (recordId: string) => {
    setSensitiveError("");
    setSensitiveSuccess("");
    try {
      if (!userToken) {
        throw new Error("Sign in to manage sensitive records");
      }
      await deleteJson<{ success: boolean; message: string }>(`/api/sensitive-data/${recordId}`, { token: userToken });
      setSensitiveSuccess("Sensitive record deleted.");
      await loadSensitiveRecords(userToken);
    } catch (error) {
      setSensitiveError(error instanceof Error ? error.message : "Failed to delete sensitive record");
    }
  };

  const hydrateConfigForm = (config: ConfigurationRecord) => {
    setSelectedConfigId(config.id);
    setConfigPrompt("");
    setConfigName(config.name);
    setConfigDescription(config.description || "");
    setConfigTask(config.task);
    const domains = Array.isArray(config.details.allowedDomains)
      ? (config.details.allowedDomains as string[]).join(", ")
      : "";
    setConfigDomains(domains);
    const steps = Array.isArray(config.details.steps) ? (config.details.steps as Array<Record<string, unknown>>) : [];
    setConfigStartUrl(String(config.details.startUrl || steps[0]?.url || ""));
    const verifyText = String(
      config.details.verifyText
      || (steps[1]?.verification as Record<string, unknown> | undefined)?.textVisible
      || ""
    );
    setConfigVerifyText(verifyText);
    const metadata =
      config.details.metadata && typeof config.details.metadata === "object"
        ? (config.details.metadata as Record<string, unknown>)
        : {};
    setConfigHighRiskKeywords(
      Array.isArray(metadata.highRiskKeywords) ? (metadata.highRiskKeywords as string[]).join(", ") : ""
    );
    setConfigAuditorKeywords(
      Array.isArray(metadata.auditorKeywords) ? (metadata.auditorKeywords as string[]).join(", ") : ""
    );
    setConfigAdvancedJson(JSON.stringify(config.details, null, 2));
  };

  const applyGeneratedConfigurationDraft = (draft: ConfigurationDraftResponse["draft"]) => {
    setSelectedConfigId("");
    setConfigName(draft.name || "");
    setConfigDescription(draft.description || "");
    setConfigTask(draft.task || "");
    setConfigDomains((draft.allowedDomains || []).join(", "));
    setConfigStartUrl(draft.startUrl || "");
    setConfigVerifyText(draft.verifyText || "");
    setConfigHighRiskKeywords((draft.highRiskKeywords || []).join(", "));
    setConfigAuditorKeywords((draft.auditorKeywords || []).join(", "));
    setConfigAdvancedJson(JSON.stringify(draft.advancedJson || { metadata: {} }, null, 2));
  };

  const buildConfigurationDetails = () => {
    const advanced = parseJsonInput(configAdvancedJson);
    const allowedDomains = configDomains
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const highRiskKeywords = configHighRiskKeywords
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const auditorKeywords = configAuditorKeywords
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const advancedMetadata =
      advanced.metadata && typeof advanced.metadata === "object" && !Array.isArray(advanced.metadata)
        ? (advanced.metadata as Record<string, unknown>)
        : {};

    return {
      ...advanced,
      agentId: "dashboard-operator",
      allowedDomains,
      startUrl: configStartUrl.trim() || undefined,
      verifyText: configVerifyText.trim() || undefined,
      metadata: {
        ...advancedMetadata,
        description: configDescription.trim(),
        intentSummary:
          String(advancedMetadata.intentSummary || configDescription.trim() || configTask.trim()).trim(),
        completionCriteria:
          String(
            advancedMetadata.completionCriteria
            || (configVerifyText.trim()
              ? `Do not finish until the page clearly shows "${configVerifyText.trim()}" or equivalent evidence that the task outcome was achieved.`
              : "Do not finish until the intended user-visible outcome is actually achieved.")
          ).trim(),
        highRiskKeywords,
        auditorKeywords
      }
    };
  };

  const launchJob = async () => {
    setLaunchError("");
    setLaunchSuccess("");
    try {
      if (!launchConfigId) {
        throw new Error("Choose a saved configuration first");
      }
      const response = await postJson<{ success: true; job: JobRecord }>(`/api/configurations/${launchConfigId}/launch`, {
        taskOverride: launchTaskOverride,
        runtimeMetadata: {
          ...(launchRuntimeNotes.trim() ? { runtimeNotes: launchRuntimeNotes.trim() } : {}),
          sensitiveDataGrants: buildSensitiveGrantPayload(launchSensitiveRecordIds)
        }
      });
      setLaunchSuccess("Process created from configuration and queued.");
      setSelectedJobId(response.job.id);
      upsertJob(response.job);
      setLaunchTaskOverride("");
      setLaunchRuntimeNotes("");
      setLaunchSensitiveRecordIds([]);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Failed to create process");
    }
  };

  const sendContext = async () => {
    if (!selectedJob) {
      setContextError("Select a process first.");
      return;
    }
    setContextError("");
    setContextSuccess("");
    try {
      const details = {
        ...parseJsonInput(contextDetails),
        sensitiveDataGrants: buildSensitiveGrantPayload(contextSensitiveRecordIds)
      };
      const response = await postJson<{ success: true; job: JobRecord; appendedSteps: number }>(
        `/api/jobs/${selectedJob.id}/context`,
        { prompt: contextPrompt, details }
      );
      setContextSuccess(
        response.appendedSteps > 0
          ? `Context sent and ${response.appendedSteps} step(s) appended.`
          : "Context sent to the selected process."
      );
      setContextPrompt("");
      setContextSensitiveRecordIds([]);
      setSelectedJob(response.job);
      upsertJob(response.job);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : "Failed to send context");
    }
  };

  const correctAndResume = async () => {
    if (!selectedJob) {
      setContextError("Select a process first.");
      return;
    }
    if (!contextPrompt.trim()) {
      setContextError("Enter a corrective prompt before resuming.");
      return;
    }
    setContextError("");
    setContextSuccess("");
    try {
      const details = {
        ...parseJsonInput(contextDetails),
        sensitiveDataGrants: buildSensitiveGrantPayload(contextSensitiveRecordIds)
      };
      const response = await postJson<{ success: true; job: JobRecord; appendedSteps: number }>(
        `/api/jobs/${selectedJob.id}/correct`,
        { prompt: contextPrompt, details }
      );
      setContextSuccess(
        response.appendedSteps > 0
          ? `Correction sent, ${response.appendedSteps} step(s) appended, and the process resumed.`
          : "Correction sent and the process resumed."
      );
      setContextPrompt("");
      setContextSensitiveRecordIds([]);
      setSelectedJob(response.job);
      upsertJob(response.job);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : "Failed to correct and resume process");
    }
  };

  const saveConfiguration = async () => {
    setConfigError("");
    setConfigSuccess("");
    try {
      const details = buildConfigurationDetails();
      if (!configName.trim() || !configTask.trim()) {
        throw new Error("Configuration name and task prompt are required");
      }

      if (!configDescription.trim() && !configStartUrl.trim() && !configVerifyText.trim()) {
        throw new Error("Provide a description, start URL, verify text, or advanced JSON guidance");
      }

      if (selectedConfigId) {
        await putJson(`/api/configurations/${selectedConfigId}`, {
          name: configName,
          description: configDescription,
          task: configTask,
          details
        });
        setConfigSuccess("Configuration updated.");
      } else {
        await postJson("/api/configurations", {
          name: configName,
          description: configDescription,
          task: configTask,
          details
        });
        setConfigSuccess("Configuration saved.");
      }
      await loadConfigurations();
      resetConfigForm();
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "Failed to save configuration");
    }
  };

  const generateConfigurationFromPrompt = async () => {
    setConfigError("");
    setConfigSuccess("");
    if (!configPrompt.trim()) {
      setConfigError("Enter an initial prompt to generate a configuration draft");
      return;
    }

    setConfigPromptBusy(true);
    try {
      const response = await postJson<{ success: true } & ConfigurationDraftResponse>("/api/configurations/generate", {
        prompt: configPrompt
      });
      applyGeneratedConfigurationDraft(response.draft);
      setConfigSuccess("Draft generated. Review the fields and edit anything before saving.");
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "Failed to generate configuration draft");
    } finally {
      setConfigPromptBusy(false);
    }
  };

  const launchFromConfiguration = async (configId: string) => {
    setConfigError("");
    setConfigSuccess("");
    try {
      const response = await postJson<{ success: true; job: JobRecord }>(`/api/configurations/${configId}/launch`, {
        taskOverride: "",
        runtimeMetadata: {
          sensitiveDataGrants: buildSensitiveGrantPayload(launchSensitiveRecordIds)
        }
      });
      upsertJob(response.job);
      setSelectedJobId(response.job.id);
      setActiveTab("monitor");
      setConfigSuccess("Configuration launched as a new process.");
      setLaunchSensitiveRecordIds([]);
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "Failed to launch configuration");
    }
  };

  return (
    <main className="at-shell">
      <div className={`at-layout ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <aside className={`at-sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
          <div className="at-sidebar-scroll">
          <div className="at-sidebar-brand">
            <div className="at-sidebar-brand-mark">
              <svg width="22" height="22" viewBox="0 0 36 36" fill="none">
                <rect width="36" height="36" rx="10" fill="url(#dashboardLogoGradient)" />
                <path d="M18 8l8 5v10l-8 5-8-5V13l8-5z" stroke="#fff" strokeWidth="2" fill="none" />
                <circle cx="18" cy="18" r="3" fill="#fff" />
                <defs>
                  <linearGradient id="dashboardLogoGradient" x1="0" y1="0" x2="36" y2="36">
                    <stop stopColor="#667eea" />
                    <stop offset="1" stopColor="#764ba2" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div>
              <div className="at-sidebar-brand-title">AgentTrust</div>
              <div className="at-sidebar-brand-subtitle">Operations Console</div>
            </div>
            <button
              className="at-btn at-btn-ghost at-sidebar-toggle"
              type="button"
              onClick={() => setSidebarCollapsed(true)}
            >
              Collapse
            </button>
          </div>

          <div className="at-sidebar-section">
            <div className="at-sidebar-label">Workspace</div>
            <div className="at-nav-list">
              {[
                { id: "monitor", label: "Monitor", hint: "Live operations", count: runningJobsCount },
                { id: "jobs", label: "Jobs", hint: "Process inventory", count: jobs.length },
                { id: "approvals", label: "Approvals", hint: "Human review", count: waitingJobsCount },
                { id: "metrics", label: "Metrics", hint: "Fleet health", count: metrics?.failedJobs ?? 0 },
                { id: "configurations", label: "Configurations", hint: "Bot profiles", count: configurations.length },
                { id: "sensitive", label: "Sensitive Data", hint: "Customer profiles", count: sensitiveRecords.length }
              ].map((item) => (
                <button
                  key={item.id}
                  className={`at-nav-button ${activeTab === item.id ? "active" : ""}`}
                  type="button"
                  onClick={() => setActiveTab(item.id as typeof activeTab)}
                >
                  <span className="at-nav-copy">
                    <span className="at-nav-title">{item.label}</span>
                    <span className="at-nav-hint">{item.hint}</span>
                  </span>
                  <span className="at-nav-count">{item.count}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="at-sidebar-section">
            <div className="at-sidebar-label">System health</div>
            <div className="at-sidebar-metrics">
              <div className="at-sidebar-metric">
                <span className="at-sidebar-metric-label">Running</span>
                <strong>{runningJobsCount}</strong>
              </div>
              <div className="at-sidebar-metric">
                <span className="at-sidebar-metric-label">Approvals</span>
                <strong>{waitingJobsCount}</strong>
              </div>
              <div className="at-sidebar-metric">
                <span className="at-sidebar-metric-label">Failed</span>
                <strong>{failedJobsCount}</strong>
              </div>
              <div className="at-sidebar-metric">
                <span className="at-sidebar-metric-label">Paused</span>
                <strong>{pausedJobsCount}</strong>
              </div>
            </div>
          </div>

          <div className="at-sidebar-section">
            <div className="at-sidebar-label">Operator context</div>
            <div className="at-sidebar-note">
              <div className="at-sidebar-note-title">Current focus</div>
              <div className="at-sidebar-note-body">
                {selectedJob
                  ? `${selectedJob.currentStep || "Selected process"} · ${selectedJob.id.slice(0, 8)}`
                  : currentTabMeta.description}
              </div>
            </div>
            <div className="at-sidebar-note">
              <div className="at-sidebar-note-title">Sensitive data access</div>
              <div className="at-sidebar-note-body">
                {currentUser
                  ? `Signed in as ${currentUser.email}. ${sensitiveRecords.length} encrypted customer profile(s) available.`
                  : "Use the Sensitive Data workspace to sign in, upload encrypted customer JSON, and attach profiles to specific runs."}
              </div>
            </div>
          </div>
          </div>
        </aside>

        <div className="at-main">
          <header className="at-page-header">
            <div className="at-page-header-copy">
              <div className="at-page-kicker">Enterprise monitoring workspace</div>
              <h1 className="at-page-title">{currentTabMeta.label}</h1>
              <p className="at-page-description">{currentTabMeta.description}</p>
              {(historyResetError || historyResetSuccess) && (
                <div className="at-header-feedback">
                  {historyResetError && <div className="at-error">{historyResetError}</div>}
                  {historyResetSuccess && <div className="at-success">{historyResetSuccess}</div>}
                </div>
              )}
            </div>
            <div className="at-page-header-actions">
              <div className="at-header-action-group">
                {sidebarCollapsed && (
                  <button
                    className="at-btn at-btn-ghost"
                    type="button"
                    onClick={() => setSidebarCollapsed(false)}
                  >
                    Expand Sidebar
                  </button>
                )}
                <button className="at-btn at-btn-ghost" type="button" onClick={() => void refreshDashboard()}>
                  Refresh
                </button>
                <button
                  className="at-btn at-btn-danger"
                  type="button"
                  onClick={() => void resetDashboardHistory()}
                  disabled={historyResetBusy}
                >
                  {historyResetBusy ? "Clearing..." : "Clear Past Activity"}
                </button>
              </div>
              <div className="at-live-pill">
                <span className="at-live-dot" />
                Live platform
              </div>
              {metrics && (
                <div className="at-header-stat">
                  <span className="at-header-stat-label">Fleet success</span>
                  <span className="at-header-stat-value">{(metrics.successRate * 100).toFixed(0)}%</span>
                </div>
              )}
              {selectedJob && (
                <div className="at-header-stat">
                  <span className="at-header-stat-label">Selected process</span>
                  <span className="at-header-stat-value">{selectedJob.id.slice(0, 8)}</span>
                </div>
              )}
            </div>
          </header>

          <div className="at-page">
            {activeTab !== "configurations" && activeTab !== "sensitive" && (
              <section className="at-overview-grid">
                <div className="at-card at-overview-card">
                  <div className="at-card-header">
                    <div>
                      <div className="at-card-title">Execution overview</div>
                      <div className="at-card-subtitle">Live operational state across workers, approvals, and customer automation queues.</div>
                    </div>
                  </div>
                  <div className="at-card-body">
                    <div className="at-kpi-grid">
                      <div className="at-kpi-card">
                        <span className="at-kpi-label">Running now</span>
                        <strong>{runningJobsCount}</strong>
                        <span className="at-kpi-footnote">Active processes executing against targets.</span>
                      </div>
                      <div className="at-kpi-card">
                        <span className="at-kpi-label">Awaiting review</span>
                        <strong>{waitingJobsCount}</strong>
                        <span className="at-kpi-footnote">Operations paused for human approval.</span>
                      </div>
                      <div className="at-kpi-card">
                        <span className="at-kpi-label">Failures</span>
                        <strong>{metrics?.failedJobs ?? failedJobsCount}</strong>
                        <span className="at-kpi-footnote">Runs that need investigation or replay.</span>
                      </div>
                      <div className="at-kpi-card">
                        <span className="at-kpi-label">Success rate</span>
                        <strong>{metrics ? `${(metrics.successRate * 100).toFixed(0)}%` : "n/a"}</strong>
                        <span className="at-kpi-footnote">Resolved from total platform job history.</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="at-card at-overview-card">
                  <div className="at-card-header">
                    <div>
                      <div className="at-card-title">Operator guidance</div>
                      <div className="at-card-subtitle">Keep launches, approvals, and sensitive profile grants aligned for each customer run.</div>
                    </div>
                  </div>
                  <div className="at-card-body">
                    <div className="at-guidance-list">
                      <div className="at-guidance-item">
                        <span className="at-guidance-heading">Configuration source</span>
                        <span className="at-guidance-copy">
                          {launchConfigId
                            ? `Ready to launch from ${configurations.find((config) => config.id === launchConfigId)?.name || "selected profile"}.`
                            : "Select a saved configuration to standardize each launch."}
                        </span>
                      </div>
                      <div className="at-guidance-item">
                        <span className="at-guidance-heading">Approval coverage</span>
                        <span className="at-guidance-copy">
                          {approvals.length > 0
                            ? `${approvals.length} high-risk action(s) are waiting for operator review.`
                            : "No pending approvals. High-risk actions will surface here automatically."}
                        </span>
                      </div>
                      <div className="at-guidance-item">
                        <span className="at-guidance-heading">Sensitive profiles</span>
                        <span className="at-guidance-copy">
                          {currentUser
                            ? `${sensitiveRecords.length} encrypted profile(s) can be attached to the next run.`
                            : "Sign in to the vault workspace to attach encrypted customer JSON to a job."}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            )}

        {activeTab === "configurations" && (
          <div className="at-grid mt-3 lg:grid-cols-[0.95fr_1.05fr]">
            <section className="at-card">
              <div className="at-card-header">
                <h2 className="at-card-title">Saved Configurations</h2>
                <button className="at-btn at-btn-ghost" type="button" onClick={resetConfigForm}>New</button>
              </div>
              <div className="at-card-body">
                <div className="at-list">
                  {configurations.map((config) => (
                    <div key={config.id} className={`at-config-card ${selectedConfigId === config.id ? "active" : ""}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold">{config.name}</div>
                          {config.description && <div className="at-subtle mt-1 text-xs">{config.description}</div>}
                          <div className="at-subtle mt-2 text-xs">{config.task}</div>
                        </div>
                        <span className="at-code at-subtle">{config.id}</span>
                      </div>
                      <div className="mt-3 flex gap-2">
                        <button className="at-btn at-btn-ghost" type="button" onClick={() => hydrateConfigForm(config)}>Edit</button>
                        <button className="at-btn at-btn-primary" type="button" onClick={() => launchFromConfiguration(config.id)}>Launch</button>
                      </div>
                    </div>
                  ))}
                  {configurations.length === 0 && <div className="at-subtle text-sm">No reusable configurations saved yet.</div>}
                </div>
              </div>
            </section>

            <section className="at-card">
              <div className="at-card-header">
                <h2 className="at-card-title">{selectedConfigId ? "Edit Configuration" : "Create Configuration"}</h2>
                <span className="at-subtle text-xs">Generate from a plain-English prompt, then edit before saving</span>
              </div>
              <div className="at-card-body space-y-4">
                <div className="at-field">
                  <label className="at-label">Initial prompt</label>
                  <textarea
                    className="at-textarea"
                    value={configPrompt}
                    onChange={(event) => setConfigPrompt(event.target.value)}
                    placeholder="Example: Create a Jira bug intake bot that opens https://company.atlassian.net, signs in, fills out the create issue form, verifies the text 'Create issue', and escalates any payment or delete actions."
                  />
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <div className="at-help">Use AI to fill all fields from this prompt. Nothing is saved until you click Save Configuration.</div>
                    <button className="at-btn at-btn-primary" type="button" onClick={generateConfigurationFromPrompt} disabled={configPromptBusy}>
                      {configPromptBusy ? "Generating..." : "Generate With AI"}
                    </button>
                  </div>
                </div>
                <div className="at-field">
                  <label className="at-label">Configuration name</label>
                  <input className="at-input" value={configName} onChange={(event) => setConfigName(event.target.value)} placeholder="Weekly Jira triage bot" />
                </div>
                <div className="at-field">
                  <label className="at-label">Description</label>
                  <input className="at-input" value={configDescription} onChange={(event) => setConfigDescription(event.target.value)} placeholder="Short explanation of what this bot is for" />
                </div>
                <div className="at-field">
                  <label className="at-label">Task prompt</label>
                  <input className="at-input" value={configTask} onChange={(event) => setConfigTask(event.target.value)} placeholder="What should the bot do?" />
                </div>
                <div className="at-field">
                  <label className="at-label">Allowed domains</label>
                  <input className="at-input" value={configDomains} onChange={(event) => setConfigDomains(event.target.value)} placeholder="jira.example.com, github.com" />
                </div>
                <div className="at-field">
                  <label className="at-label">Start URL</label>
                  <input className="at-input" value={configStartUrl} onChange={(event) => setConfigStartUrl(event.target.value)} placeholder="https://example.com/path" />
                </div>
                <div className="at-field">
                  <label className="at-label">Text to verify on page</label>
                  <input className="at-input" value={configVerifyText} onChange={(event) => setConfigVerifyText(event.target.value)} placeholder="Visible text that confirms the bot is on the right page" />
                </div>
                <div className="at-field">
                  <label className="at-label">High-risk keywords</label>
                  <input className="at-input" value={configHighRiskKeywords} onChange={(event) => setConfigHighRiskKeywords(event.target.value)} placeholder="payment, wire, billing, submit, delete" />
                </div>
                <div className="at-field">
                  <label className="at-label">Auditor course-correction keywords</label>
                  <input className="at-input" value={configAuditorKeywords} onChange={(event) => setConfigAuditorKeywords(event.target.value)} placeholder="login, summary, description, form, account" />
                </div>
                <div className="at-field">
                  <label className="at-label">Advanced JSON details</label>
                  <textarea className="at-textarea" value={configAdvancedJson} onChange={(event) => setConfigAdvancedJson(event.target.value)} />
                  <div className="at-help">
                    Optional advanced settings. You can provide extra metadata or full step overrides here. Keyword fields are saved into configuration metadata for future policy and auditor use.
                  </div>
                </div>
                {configError && <div className="at-error">{configError}</div>}
                {configSuccess && <div className="at-success">{configSuccess}</div>}
                <div className="flex justify-end gap-2">
                  <button className="at-btn at-btn-ghost" type="button" onClick={resetConfigForm}>Reset</button>
                  <button className="at-btn at-btn-primary" type="button" onClick={saveConfiguration}>
                    {selectedConfigId ? "Update Configuration" : "Save Configuration"}
                  </button>
                </div>
              </div>
            </section>
          </div>
        )}

        {activeTab === "sensitive" && (
          <div className="at-grid mt-3 lg:grid-cols-[0.92fr_1.08fr]">
            <section className="at-card">
              <div className="at-card-header">
                <div>
                  <h2 className="at-card-title">Vault Access</h2>
                  <div className="at-subtle text-xs">Sign in once to upload JSON and store it encrypted in Postgres.</div>
                </div>
                {currentUser && (
                  <button className="at-btn at-btn-ghost" type="button" onClick={logoutSensitiveVault}>Sign out</button>
                )}
              </div>
              <div className="at-card-body space-y-4">
                {currentUser ? (
                  <div className="at-config-card">
                    <div className="text-sm font-semibold">{currentUser.name || currentUser.email}</div>
                    <div className="at-subtle mt-1 text-xs">{currentUser.email}</div>
                    <div className="at-help mt-3">Uploads from this tab are encrypted on the backend and only used through `vault://...` references.</div>
                  </div>
                ) : (
                  <>
                    <div className="at-field">
                      <label className="at-label">Email</label>
                      <input className="at-input" value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="user@example.com" />
                    </div>
                    <div className="at-field">
                      <label className="at-label">Password</label>
                      <input className="at-input" type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="Enter your password" />
                    </div>
                    <div className="at-help">Use your AgentTrust user account. The dashboard stores only the JWT needed to call encrypted vault routes.</div>
                    <div className="flex justify-end">
                      <button className="at-btn at-btn-primary" type="button" onClick={loginSensitiveVault} disabled={authBusy}>
                        {authBusy ? "Signing in..." : "Sign In"}
                      </button>
                    </div>
                  </>
                )}
                {authError && <div className="at-error">{authError}</div>}
                {authSuccess && <div className="at-success">{authSuccess}</div>}
              </div>
            </section>

            <section className="at-card">
              <div className="at-card-header">
                <div>
                  <h2 className="at-card-title">Upload Sensitive JSON</h2>
                  <div className="at-subtle text-xs">Paste a JSON object or upload a file. The backend encrypts it before saving.</div>
                </div>
                <button className="at-btn at-btn-ghost" type="button" onClick={resetSensitiveForm}>Reset</button>
              </div>
              <div className="at-card-body space-y-4">
                <div className="at-field">
                  <label className="at-label">Label</label>
                  <input className="at-input" value={sensitiveLabel} onChange={(event) => setSensitiveLabel(event.target.value)} placeholder="Customer onboarding batch A" />
                </div>
                <div className="at-field">
                  <label className="at-label">Reference key</label>
                  <input className="at-input" value={sensitiveReferenceKey} onChange={(event) => setSensitiveReferenceKey(event.target.value)} placeholder="customer_onboarding_a" />
                  <div className="at-help">Optional. Used to generate references like `vault://customer_onboarding_a/ssn`.</div>
                </div>
                <div className="at-grid lg:grid-cols-[1fr_1fr]">
                  <div className="at-field">
                    <label className="at-label">Category</label>
                    <input className="at-input" value={sensitiveCategory} onChange={(event) => setSensitiveCategory(event.target.value)} placeholder="pii" />
                  </div>
                  <div className="at-field">
                    <label className="at-label">Allowed domains</label>
                    <input className="at-input" value={sensitiveAllowedDomains} onChange={(event) => setSensitiveAllowedDomains(event.target.value)} placeholder="example.com, app.example.com" />
                  </div>
                </div>
                <div className="at-field">
                  <label className="at-label">Tags</label>
                  <input className="at-input" value={sensitiveTags} onChange={(event) => setSensitiveTags(event.target.value)} placeholder="onboarding, customer, restricted" />
                </div>
                <div className="at-field">
                  <label className="at-label">Upload JSON file</label>
                  <input className="at-input" type="file" accept=".json,application/json" onChange={handleSensitiveFileUpload} />
                </div>
                <div className="at-field">
                  <label className="at-label">Sensitive JSON</label>
                  <textarea className="at-textarea" value={sensitiveJsonInput} onChange={(event) => setSensitiveJsonInput(event.target.value)} />
                  <div className="at-help">Paste a JSON object only. Do not paste raw PII into prompts after this; use the generated vault references instead.</div>
                </div>
                <div className="at-config-card">
                  <div className="text-sm font-semibold">Preview generated references</div>
                  {sensitivePreview.error ? (
                    <div className="at-error mt-3">{sensitivePreview.error}</div>
                  ) : sensitivePreview.fieldPaths.length > 0 ? (
                    <div className="mt-3 space-y-2">
                      {sensitivePreview.fieldPaths.map((fieldPath) => {
                        const reference = `vault://${previewReferenceKey}/${fieldPath}`;
                        return (
                          <div key={fieldPath} className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <div className="text-sm font-medium">{fieldPath}</div>
                              <div className="at-code at-subtle mt-1 text-xs break-all">{reference}</div>
                            </div>
                            <button className="at-btn at-btn-ghost" type="button" onClick={() => copyToClipboard(reference, `Copied ${fieldPath} reference.`)}>
                              Copy
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="at-subtle mt-3 text-sm">Add at least one field to generate preview references.</div>
                  )}
                </div>
                {sensitiveError && <div className="at-error">{sensitiveError}</div>}
                {sensitiveSuccess && <div className="at-success">{sensitiveSuccess}</div>}
                <div className="flex justify-end">
                  <button className="at-btn at-btn-primary" type="button" onClick={saveSensitiveRecord} disabled={!userToken}>
                    Save Encrypted Record
                  </button>
                </div>
              </div>
            </section>

            <section className="at-card">
              <div className="at-card-header">
                <div>
                  <h2 className="at-card-title">Latest Saved References</h2>
                  <div className="at-subtle text-xs">Copy these into process details, configuration metadata, or operator JSON.</div>
                </div>
              </div>
              <div className="at-card-body">
                {Object.keys(latestFieldRefs).length > 0 ? (
                  <div className="at-list">
                    {Object.entries(latestFieldRefs).map(([fieldPath, reference]) => (
                      <div key={fieldPath} className="at-config-card">
                        <div className="text-sm font-semibold">{fieldPath}</div>
                        <div className="at-code at-subtle mt-2 text-xs break-all">{reference}</div>
                        <div className="mt-3 flex justify-end">
                          <button className="at-btn at-btn-primary" type="button" onClick={() => copyToClipboard(reference, `Copied ${fieldPath} reference.`)}>
                            Copy Reference
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="at-subtle text-sm">Save a record to see a ready-to-copy reference list here.</div>
                )}
              </div>
            </section>

            <section className="at-card">
              <div className="at-card-header">
                <div>
                  <h2 className="at-card-title">Saved Encrypted Records</h2>
                  <div className="at-subtle text-xs">{sensitiveRecords.length} record(s)</div>
                </div>
              </div>
              <div className="at-card-body">
                {sensitiveRecords.length > 0 ? (
                  <div className="at-list">
                    {sensitiveRecords.map((record) => (
                      <div key={record.id} className="at-config-card">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold">{record.label || record.referenceKey}</div>
                            <div className="at-code at-subtle mt-1 text-xs">{record.referenceKey}</div>
                          </div>
                          <span className="at-status-badge queued">{record.category || "pii"}</span>
                        </div>
                        <div className="at-subtle mt-2 text-xs">
                          Fields: {record.fieldNames.join(", ") || "None"}<br />
                          Domains: {record.allowedDomains.join(", ") || "Any approved domain"}<br />
                          Tags: {record.tags.join(", ") || "None"}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {record.fieldNames.slice(0, 6).map((fieldName) => {
                            const reference = `vault://${record.referenceKey}/${fieldName}`;
                            return (
                              <button key={fieldName} className="at-btn at-btn-ghost" type="button" onClick={() => copyToClipboard(reference, `Copied ${fieldName} reference.`)}>
                                Copy {fieldName}
                              </button>
                            );
                          })}
                          <button className="at-btn at-btn-danger" type="button" onClick={() => deleteSensitiveRecord(record.id)}>
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="at-subtle text-sm">
                    {userToken ? "No encrypted records saved yet." : "Sign in to view and manage encrypted records."}
                  </div>
                )}
              </div>
            </section>
          </div>
        )}

        {activeTab !== "configurations" && activeTab !== "sensitive" && (
          <>
        <section className="at-card mt-3">
          <div className="at-card-header">
            <h2 className="at-card-title">Launch From Configuration</h2>
            <span className="at-subtle text-xs">Use a saved bot profile instead of writing raw JSON</span>
          </div>
          <div className="at-card-body space-y-4">
            <div className="at-field">
              <label className="at-label" htmlFor="launch-configuration">Saved configuration</label>
              <select
                id="launch-configuration"
                className="at-input"
                value={launchConfigId}
                onChange={(event) => setLaunchConfigId(event.target.value)}
              >
                <option value="">Select configuration</option>
                {configurations.map((config) => (
                  <option key={config.id} value={config.id}>{config.name}</option>
                ))}
              </select>
            </div>
            <div className="at-field">
              <label className="at-label" htmlFor="launch-task-override">Optional task override</label>
              <input
                id="launch-task-override"
                className="at-input"
                value={launchTaskOverride}
                onChange={(event) => setLaunchTaskOverride(event.target.value)}
                placeholder="Optional runtime override for the selected configuration"
              />
            </div>
            <div className="at-field">
              <label className="at-label" htmlFor="launch-runtime-notes">Runtime notes</label>
              <textarea
                id="launch-runtime-notes"
                className="at-textarea"
                value={launchRuntimeNotes}
                onChange={(event) => setLaunchRuntimeNotes(event.target.value)}
              />
              <div className="at-help">Use runtime notes for extra context. Edit steps, approval keywords, and auditor keywords in the Configurations tab.</div>
            </div>
            <div className="at-field">
              <label className="at-label">Customer profiles allowed for this run</label>
              {currentUser ? (
                sensitiveRecords.length > 0 ? (
                  <div className="space-y-2">
                    {sensitiveRecords.map((record) => (
                      <label key={`launch-${record.id}`} className="at-config-card flex cursor-pointer items-start gap-3">
                        <input
                          type="checkbox"
                          checked={launchSensitiveRecordIds.includes(record.id)}
                          onChange={() => toggleSensitiveRecordSelection(record.id, setLaunchSensitiveRecordIds)}
                        />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold">{record.label || record.referenceKey}</div>
                          <div className="at-code at-subtle mt-1 text-xs">{record.referenceKey}</div>
                          <div className="at-subtle mt-2 text-xs">Fields: {record.fieldNames.join(", ") || "None"}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="at-subtle text-sm">No encrypted customer profiles saved yet. Add them in the `Sensitive Data` tab first.</div>
                )
              ) : (
                <div className="at-subtle text-sm">Sign in in the `Sensitive Data` tab to attach specific customer profiles to this run.</div>
              )}
              <div className="at-help">Only attached profiles can be used by this operation when resolving `vault://...` references.</div>
            </div>
            {launchError && <div className="at-error">{launchError}</div>}
            {launchSuccess && <div className="at-success">{launchSuccess}</div>}
            <div className="flex justify-end">
              <button className="at-btn at-btn-primary" type="button" onClick={launchJob}>
                Spin Up Process
              </button>
            </div>
          </div>
        </section>

        {(activeTab === "monitor" || activeTab === "metrics") && metrics && (
          <section className="at-stats mt-3">
            <div className="at-stat primary">
              <span className="at-stat-num">{metrics.totalJobs}</span>
              <span className="at-stat-label">Jobs</span>
            </div>
            <div className="at-stat danger">
              <span className="at-stat-num">{metrics.failedJobs}</span>
              <span className="at-stat-label">Failed</span>
            </div>
            <div className="at-stat warning">
              <span className="at-stat-num">{metrics.waitingApproval}</span>
              <span className="at-stat-label">Approval</span>
            </div>
            <div className="at-stat purple">
              <span className="at-stat-num">{metrics.averageRetries.toFixed(1)}</span>
              <span className="at-stat-label">Avg Retries</span>
            </div>
          </section>
        )}

        {(activeTab === "monitor" || activeTab === "jobs") && (
          <div className={`at-process-layout mt-3 ${selectedJob ? "" : "at-process-layout-empty"}`}>
            <div className="at-process-sidebar">
              <section className="at-card">
                <div className="at-card-header">
                  <div>
                    <h2 className="at-card-title">Processes</h2>
                    <div className="at-subtle text-xs">
                      {sortedJobs.length} total{selectedJob ? ` · selected ${selectedJob.id.slice(0, 8)}` : ""}
                    </div>
                  </div>
                </div>
                <div className="at-card-body space-y-3">
                  {sortedJobs.map((job) => (
                    <button
                      key={job.id}
                      className={`at-job-button ${selectedJobId === job.id ? "active" : ""}`}
                      onClick={() => setSelectedJobId(job.id)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="at-job-title-row">
                            <span className="at-job-title">{job.currentStep || "Queued process"}</span>
                            {selectedJobId === job.id && <span className="at-selected-pill">Selected</span>}
                          </div>
                          <div className="at-subtle mt-1 text-xs">{job.id}</div>
                        </div>
                        <span className={`at-status-badge ${statusTone(job.status)}`}>{formatStatusLabel(job.status)}</span>
                      </div>
                      <div className="at-job-meta">
                        <span>{job.progress || 0}% complete</span>
                        <span>{job.error ? "Needs attention" : "Healthy"}</span>
                      </div>
                      <div className="at-progress">
                        <div className="at-progress-bar" style={{ width: `${job.progress || 0}%` }} />
                      </div>
                    </button>
                  ))}
                  {sortedJobs.length === 0 && <div className="at-subtle text-sm">No jobs yet.</div>}
                </div>
              </section>

              {activeTab === "monitor" && (
                <section className="at-card">
                  <div className="at-card-header">
                    <h2 className="at-card-title">Approval Inbox</h2>
                    <span className="at-subtle text-xs">{approvals.length} pending</span>
                  </div>
                  <div className="at-card-body space-y-3">
                    {approvals.map((approval) => (
                      <div key={approval.id} className="at-approval-card">
                        <div className="text-sm font-medium">{approval.action}</div>
                        <div className="mt-1 text-xs" style={{ color: "var(--c-text-2)" }}>{approval.policyReason}</div>
                        <div className="mt-3 flex gap-2">
                          <button
                            className="at-btn at-btn-success"
                            onClick={() => postJson(`/api/approvals/${approval.id}/decision`, { approved: true })}
                          >
                            Approve
                          </button>
                          <button
                            className="at-btn at-btn-danger"
                            onClick={() => postJson(`/api/approvals/${approval.id}/decision`, { approved: false })}
                          >
                            Reject
                          </button>
                        </div>
                      </div>
                    ))}
                    {approvals.length === 0 && <div className="at-subtle text-sm">No pending approvals.</div>}
                  </div>
                </section>
              )}
            </div>

            <div className="at-process-detail">
              {selectedJob ? (
                <>
                  <section className="at-card at-selected-card">
                    <div className="at-card-header">
                      <div>
                        <div className="at-selected-label">Selected Process</div>
                        <h2 className="at-card-title">{selectedJob.currentStep || "Awaiting work"}</h2>
                        <div className="at-subtle text-xs">{selectedJob.id}</div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`at-status-badge ${statusTone(selectedJob.status)}`}>{formatStatusLabel(selectedJob.status)}</span>
                        <button className="at-btn at-btn-ghost" onClick={() => postJson(`/api/jobs/${selectedJob.id}/pause`)}>
                          Pause
                        </button>
                        <button className="at-btn at-btn-primary" onClick={() => postJson(`/api/jobs/${selectedJob.id}/resume`)}>
                          Resume
                        </button>
                        <button className="at-btn at-btn-danger" onClick={() => postJson(`/api/jobs/${selectedJob.id}/cancel`)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                    <div className="at-card-body">
                      <div className="at-kpi-grid">
                        <div className="at-kpi-card">
                          <div className="at-kpi-label">Status</div>
                          <div className="at-kpi-value">{formatStatusLabel(selectedJob.status)}</div>
                        </div>
                        <div className="at-kpi-card">
                          <div className="at-kpi-label">Progress</div>
                          <div className="at-kpi-value">{selectedJob.progress || 0}%</div>
                        </div>
                        <div className="at-kpi-card">
                          <div className="at-kpi-label">Current Step</div>
                          <div className="at-kpi-value">{selectedJob.currentStep || "None"}</div>
                        </div>
                        <div className="at-kpi-card">
                          <div className="at-kpi-label">Replay Events</div>
                          <div className="at-kpi-value">{replayCount}</div>
                        </div>
                      </div>
                      <div className="at-progress at-progress-lg">
                        <div className="at-progress-bar" style={{ width: `${selectedJob.progress || 0}%` }} />
                      </div>
                      {selectedJob.error && <div className="at-error mt-3">Error: {selectedJob.error}</div>}
                      {selectedJobSensitiveGrants.length > 0 && (
                        <div className="mt-3 space-y-2">
                          <div className="at-label">Attached customer profiles</div>
                          <div className="flex flex-wrap gap-2">
                            {selectedJobSensitiveGrants.map((grant, index) => (
                              <span key={`${grant.referenceKey || grant.id || "grant"}-${index}`} className="at-status-badge queued">
                                {grant.label || grant.referenceKey || grant.id}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </section>

                  <div className="at-grid mt-3 lg:grid-cols-[0.95fr_1.05fr]">
                    <section className="at-card">
                      <div className="at-card-header">
                        <h2 className="at-card-title">Prompt Selected Process</h2>
                      </div>
                      <div className="at-card-body">
                        <div className="space-y-4">
                          <div className="at-field">
                            <label className="at-label" htmlFor="context-prompt">Operator prompt</label>
                            <input
                              id="context-prompt"
                              className="at-input"
                              value={contextPrompt}
                              onChange={(event) => setContextPrompt(event.target.value)}
                              placeholder="Add instructions or corrective context for this process"
                            />
                          </div>
                          <div className="at-field">
                            <label className="at-label" htmlFor="context-details">JSON details</label>
                            <textarea
                              id="context-details"
                              className="at-textarea"
                              value={contextDetails}
                              onChange={(event) => setContextDetails(event.target.value)}
                            />
                            <div className="at-help">
                              Use `appendSteps` to add queued work. Other JSON is stored with the operator prompt.
                            </div>
                          </div>
                          <div className="at-field">
                            <label className="at-label">Customer profiles allowed for this process</label>
                            {currentUser ? (
                              sensitiveRecords.length > 0 ? (
                                <div className="space-y-2">
                                  {sensitiveRecords.map((record) => (
                                    <label key={`context-${record.id}`} className="at-config-card flex cursor-pointer items-start gap-3">
                                      <input
                                        type="checkbox"
                                        checked={contextSensitiveRecordIds.includes(record.id)}
                                        onChange={() => toggleSensitiveRecordSelection(record.id, setContextSensitiveRecordIds)}
                                      />
                                      <div className="min-w-0">
                                        <div className="text-sm font-semibold">{record.label || record.referenceKey}</div>
                                        <div className="at-code at-subtle mt-1 text-xs">{record.referenceKey}</div>
                                        <div className="at-subtle mt-2 text-xs">Fields: {record.fieldNames.join(", ") || "None"}</div>
                                      </div>
                                    </label>
                                  ))}
                                </div>
                              ) : (
                                <div className="at-subtle text-sm">No encrypted customer profiles saved yet. Add them in the `Sensitive Data` tab first.</div>
                              )
                            ) : (
                              <div className="at-subtle text-sm">Sign in in the `Sensitive Data` tab to attach customer profiles to this process.</div>
                            )}
                            <div className="at-help">This updates which customer profiles this specific operation can use. Unattached profiles stay blocked even if a prompt mentions their `vault://...` references.</div>
                          </div>
                          {contextError && <div className="at-error">{contextError}</div>}
                          {contextSuccess && <div className="at-success">{contextSuccess}</div>}
                          <div className="flex justify-end gap-2">
                            <button className="at-btn at-btn-ghost" type="button" onClick={correctAndResume}>
                              Correct + Resume
                            </button>
                            <button className="at-btn at-btn-primary" type="button" onClick={sendContext}>
                              Send Prompt
                            </button>
                          </div>
                        </div>
                      </div>
                    </section>

                    <section className="at-card">
                      <div className="at-card-header">
                        <h2 className="at-card-title">Step Timeline</h2>
                        <span className="at-subtle text-xs">{selectedTimeline.length} steps</span>
                      </div>
                      <div className="at-card-body space-y-3">
                        <div className="at-goal-tracker">
                          {selectedTimeline.map((step, index) => {
                            const failureDetail = stepFailureDetail(step, selectedJob?.error);
                            const generatedActions = stepGeneratedActions(step, replayEvents);
                            return (
                            <div key={step.id} className="at-goal-item">
                              <div className="at-goal-rail">
                                <div className={`at-goal-node ${statusTone(step.status)}`}>{stepMarkerText(step)}</div>
                                {index < selectedTimeline.length - 1 && (
                                  <div className={`at-goal-line ${statusTone(step.status) === "completed" ? "completed" : ""}`} />
                                )}
                              </div>
                              <div className={`at-goal-card ${step.status === "failed" ? "failed" : ""}`}>
                                <div className="flex items-center justify-between gap-3">
                                  <div>
                                    <div className="text-xs at-subtle">Goal {step.sequence + 1}</div>
                                    <div className="text-sm font-semibold">{step.name}</div>
                                  </div>
                                  <span className={`at-status-badge ${statusTone(step.status)}`}>{formatStatusLabel(step.status)}</span>
                                </div>
                                <div className="at-goal-summary">{stepOutcomeSummary(step)}</div>
                                {generatedActions.length > 0 && (
                                  <div className="mt-3 space-y-1">
                                    <div className="at-goal-problem-label">Generated actions</div>
                                    {generatedActions.map((action, actionIndex) => (
                                      <div key={`${step.id}-action-${actionIndex}`} className="at-subtle text-xs">
                                        {action}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <div className="at-subtle mt-2 text-xs">
                                  Retries: {step.retryCount} · Failure type: {formatStatusLabel(step.failureType)}
                                </div>
                                {failureDetail && (step.failureType !== "NONE" || step.status === "failed") && (
                                  <div className="at-goal-problem">
                                    <div className="at-goal-problem-label">What went wrong</div>
                                    <div className="text-xs">{failureDetail}</div>
                                  </div>
                                )}
                              </div>
                            </div>
                            );
                          })}
                        </div>
                        {selectedTimeline.length === 0 && <div className="at-subtle text-sm">No steps yet.</div>}
                      </div>
                    </section>
                  </div>

                  <section className="at-card mt-3">
                    <div className="at-card-header">
                      <h2 className="at-card-title">Process Context &amp; Replay</h2>
                      <span className="at-subtle text-xs">{replayCount} captured events</span>
                    </div>
                    <div className="at-card-body">
                      {operatorPrompts.length > 0 && (
                        <div className="space-y-2 pb-4">
                          <div className="at-label">Recent operator prompts</div>
                          {operatorPrompts.slice().reverse().slice(0, 3).map((entry, index) => (
                            <div key={`${entry.createdAt}-${index}`} className="at-step-card">
                              <div className="text-sm font-medium">{entry.prompt}</div>
                              <div className="at-subtle mt-1 text-xs">{new Date(entry.createdAt).toLocaleString()}</div>
                              {entry.details && Object.keys(entry.details).length > 0 && (
                                <pre className="at-subtle mt-2 overflow-auto text-xs">{JSON.stringify(entry.details, null, 2)}</pre>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="at-replay-panel text-sm">
                        {replayEvents.length > 0 ? (
                          <>
                          {replayAuditCards(replayEvents).length > 0 ? (
                          <div className="at-replay-grid">
                            {replayAuditCards(replayEvents).map((entry) => (
                              <div key={entry.id} className="at-step-card">
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-sm font-medium">{replayTitle(entry.eventType, entry.payload)}</span>
                                  <span className="at-subtle text-xs">#{entry.sequence}</span>
                                </div>
                                {entry.eventType === "progress.line" && typeof entry.payload.line === "string" && (
                                  <div className="at-subtle mt-1 text-xs">
                                    {entry.payload.line.split("|", 1)[0]}
                                  </div>
                                )}
                                {typeof entry.payload.url === "string" && (
                                  <div className="at-subtle mt-1 text-xs">{entry.payload.url}</div>
                                )}
                                {typeof entry.payload.screenshotBase64 === "string" && (
                                  <img
                                    alt={`${entry.eventType} screenshot`}
                                    className="mt-2 w-full rounded border"
                                    src={`data:${typeof entry.payload.screenshotMimeType === "string" ? entry.payload.screenshotMimeType : "image/jpeg"};base64,${entry.payload.screenshotBase64}`}
                                  />
                                )}
                                {replaySummary(entry.payload) && (
                                  <div className="at-subtle mt-2 text-xs">{replaySummary(entry.payload)}</div>
                                )}
                              </div>
                            ))}
                          </div>
                          ) : (
                            <div className="at-subtle text-sm">No mutating action screenshots yet for this process.</div>
                          )}
                          {replayBackgroundEvents(replayEvents).length > 0 && (
                            <details className="mt-4">
                              <summary className="cursor-pointer at-subtle text-xs">
                                Background updates ({replayBackgroundEvents(replayEvents).length})
                              </summary>
                              <div className="mt-3 space-y-2">
                                {replayBackgroundEvents(replayEvents).map((entry) => (
                                  <div key={entry.id} className="at-step-card">
                                    <div className="flex items-center justify-between gap-3">
                                      <span className="text-sm font-medium">{replayTitle(entry.eventType, entry.payload)}</span>
                                      <span className="at-subtle text-xs">#{entry.sequence}</span>
                                    </div>
                                    {typeof entry.payload.url === "string" && (
                                      <div className="at-subtle mt-1 text-xs">{entry.payload.url}</div>
                                    )}
                                    {replaySummary(entry.payload) && (
                                      <div className="at-subtle mt-2 text-xs">{replaySummary(entry.payload)}</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}
                          </>
                        ) : (
                          <div className="at-subtle text-sm">No replay events yet for this process.</div>
                        )}
                      </div>
                    </div>
                  </section>
                </>
              ) : (
                <section className="at-card at-empty-selection-card">
                  <div className="at-card-body">
                    <div className="at-empty-state">
                      <div className="at-empty-state-title">Choose a process to inspect</div>
                      <div className="at-empty-state-copy">
                        {sortedJobs.length > 0
                          ? "Select a process from the left to inspect status, steps, prompts, approvals, and replay."
                          : "Launch a process to populate the queue, then select it here to review status, steps, and replay."}
                      </div>
                    </div>
                  </div>
                </section>
              )}
            </div>
          </div>
        )}

        {activeTab === "approvals" && (
          <section className="at-card mt-3">
            <div className="at-card-header">
              <h2 className="at-card-title">Approval Inbox</h2>
              <span className="at-subtle text-xs">{approvals.length} pending decisions</span>
            </div>
            <div className="at-card-body space-y-3">
              {approvals.map((approval) => (
                <div key={approval.id} className="at-approval-card">
                  <div className="text-sm font-medium">{approval.action}</div>
                  <div className="mt-1 text-xs" style={{ color: "var(--c-text-2)" }}>{approval.policyReason}</div>
                  <div className="mt-3 flex gap-2">
                    <button
                      className="at-btn at-btn-success"
                      onClick={() => postJson(`/api/approvals/${approval.id}/decision`, { approved: true })}
                    >
                      Approve
                    </button>
                    <button
                      className="at-btn at-btn-danger"
                      onClick={() => postJson(`/api/approvals/${approval.id}/decision`, { approved: false })}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))}
              {approvals.length === 0 && <div className="at-subtle text-sm">No pending approvals.</div>}
            </div>
          </section>
        )}

        {activeTab === "metrics" && (
          <div className="at-grid mt-3 lg:grid-cols-[1fr]">
            <section className="at-card">
              <div className="at-card-header">
                <div>
                  <h2 className="at-card-title">Metrics Dashboard</h2>
                  <div className="at-card-subtitle">Review current platform health, then clear historical activity to evaluate only what is still active.</div>
                </div>
              </div>
              <div className="at-card-body">
                {metrics ? (
                  <div className="at-metrics-layout">
                    <div className="at-metrics-panel">
                      <div className="at-metrics-panel-title">Current snapshot</div>
                      <div className="at-metric-list">
                        <div className="at-metric-row">
                          <span>Completed runs</span>
                          <strong>{metrics.completedJobs}</strong>
                        </div>
                        <div className="at-metric-row">
                          <span>Failed runs</span>
                          <strong>{metrics.failedJobs}</strong>
                        </div>
                        <div className="at-metric-row">
                          <span>Average execution</span>
                          <strong>{Math.round(metrics.averageExecutionMs)} ms</strong>
                        </div>
                        <div className="at-metric-row">
                          <span>Average retries</span>
                          <strong>{metrics.averageRetries.toFixed(1)}</strong>
                        </div>
                      </div>
                    </div>

                    <div className="at-metrics-panel">
                      <div className="at-metrics-panel-title">Failure breakdown</div>
                      {Object.keys(metrics.failureBreakdown).length > 0 ? (
                        <div className="at-metric-list">
                          {Object.entries(metrics.failureBreakdown).map(([key, value]) => (
                            <div key={key} className="at-metric-row">
                              <span>{key}</span>
                              <strong>{value}</strong>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="at-subtle text-sm">No failure categories recorded in the current history window.</div>
                      )}
                    </div>

                    <div className="at-metrics-panel at-metrics-panel-wide">
                      <div className="at-metrics-panel-title">Workspace hygiene</div>
                      <div className="at-help">
                        Clear past activity to remove finished process runs, replay history, completed approvals, worker history, and logged actions while keeping current active jobs visible.
                      </div>
                      <div className="at-metrics-actions">
                        <button className="at-btn at-btn-ghost" type="button" onClick={() => void refreshDashboard()}>
                          Refresh Status
                        </button>
                        <button
                          className="at-btn at-btn-danger"
                          type="button"
                          onClick={() => void resetDashboardHistory()}
                          disabled={historyResetBusy}
                        >
                          {historyResetBusy ? "Clearing..." : "Clear Historical Activity"}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="at-subtle text-sm">Loading metrics...</div>
                )}
              </div>
            </section>
          </div>
        )}
          </>
        )}
          </div>
        </div>
      </div>
    </main>
  );
}
