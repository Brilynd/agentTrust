"use client";

import { useEffect, useMemo, useState } from "react";

import { getJson, postJson } from "../lib/api";
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

type JobRecord = {
  id: string;
  status: string;
  progress: number;
  currentStep?: string | null;
  error?: string | null;
  metadata?: {
    operatorPrompts?: OperatorPromptRecord[];
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

type ConfigurationRecord = {
  id: string;
  name: string;
  description?: string;
  task: string;
  details: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export default function DashboardPage() {
  const { jobs, approvals, selectedJobId, setJobs, upsertJob, setApprovals, setSelectedJobId } = useAgentsStore();
  const [selectedJob, setSelectedJob] = useState<JobRecord | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse["metrics"] | null>(null);
  const [replayCount, setReplayCount] = useState(0);
  const [activeTab, setActiveTab] = useState<"monitor" | "jobs" | "approvals" | "metrics" | "configurations">("monitor");
  const [launchTask, setLaunchTask] = useState("");
  const [launchDetails, setLaunchDetails] = useState(`{
  "agentId": "dashboard-operator",
  "allowedDomains": ["example.com"],
  "metadata": {
    "goal": "Replace with your own task details"
  },
  "steps": [
    {
      "id": "step-1",
      "name": "Open homepage",
      "action": "goto",
      "url": "https://example.com",
      "verification": {
        "urlIncludes": "example.com"
      }
    }
  ]
}`);
  const [launchError, setLaunchError] = useState("");
  const [launchSuccess, setLaunchSuccess] = useState("");
  const [contextPrompt, setContextPrompt] = useState("");
  const [contextDetails, setContextDetails] = useState(`{
  "appendSteps": []
}`);
  const [contextError, setContextError] = useState("");
  const [contextSuccess, setContextSuccess] = useState("");
  const [configurations, setConfigurations] = useState<ConfigurationRecord[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState<string>("");
  const [configName, setConfigName] = useState("");
  const [configDescription, setConfigDescription] = useState("");
  const [configTask, setConfigTask] = useState("");
  const [configDomains, setConfigDomains] = useState("");
  const [configStartUrl, setConfigStartUrl] = useState("");
  const [configVerifyText, setConfigVerifyText] = useState("");
  const [configAdvancedJson, setConfigAdvancedJson] = useState(`{
  "metadata": {
    "notes": "Optional advanced fields"
  }
}`);
  const [configError, setConfigError] = useState("");
  const [configSuccess, setConfigSuccess] = useState("");

  const loadSelectedJob = async (jobId: string) => {
    const { job } = await getJson<{ job: JobRecord }>(`/api/jobs/${jobId}`);
    setSelectedJob(job);
    const replay = await getJson<ReplayResponse>(`/api/replays/${jobId}`);
    setReplayCount(replay.replay.length);
  };

  const loadConfigurations = async () => {
    const data = await getJson<{ configurations: ConfigurationRecord[] }>("/api/configurations");
    setConfigurations(data.configurations);
  };

  const parseJsonInput = (value: string) => {
    if (!value.trim()) {
      return {};
    }
    return JSON.parse(value) as Record<string, unknown>;
  };

  useEffect(() => {
    void Promise.all([
      getJson<JobsResponse>("/api/jobs").then((data) => setJobs(data.jobs)),
      getJson<ApprovalsResponse>("/api/approvals").then((data) => setApprovals(data.approvals)),
      getJson<MetricsResponse>("/api/metrics/summary").then((data) => setMetrics(data.metrics)),
      loadConfigurations()
    ]);
  }, [setApprovals, setJobs]);

  useEffect(() => {
    socket.on("job.created", upsertJob);
    socket.on("job.updated", upsertJob);
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
    socket.on("replay.updated", async ({ jobId }: { jobId: string }) => {
      if (jobId === selectedJobId) {
        const replay = await getJson<ReplayResponse>(`/api/replays/${jobId}`);
        setReplayCount(replay.replay.length);
      }
    });
    return () => {
      socket.off("job.created", upsertJob);
      socket.off("job.updated", upsertJob);
      socket.off("job.context_added");
      socket.off("approval.created");
      socket.off("approval.updated");
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

  const resetConfigForm = () => {
    setSelectedConfigId("");
    setConfigName("");
    setConfigDescription("");
    setConfigTask("");
    setConfigDomains("");
    setConfigStartUrl("");
    setConfigVerifyText("");
    setConfigAdvancedJson(`{
  "metadata": {
    "notes": "Optional advanced fields"
  }
}`);
  };

  const hydrateConfigForm = (config: ConfigurationRecord) => {
    setSelectedConfigId(config.id);
    setConfigName(config.name);
    setConfigDescription(config.description || "");
    setConfigTask(config.task);
    const domains = Array.isArray(config.details.allowedDomains)
      ? (config.details.allowedDomains as string[]).join(", ")
      : "";
    setConfigDomains(domains);
    const steps = Array.isArray(config.details.steps) ? (config.details.steps as Array<Record<string, unknown>>) : [];
    setConfigStartUrl(String(steps[0]?.url || ""));
    const verifyText =
      String((steps[1]?.verification as Record<string, unknown> | undefined)?.textVisible || "");
    setConfigVerifyText(verifyText);
    setConfigAdvancedJson(JSON.stringify(config.details, null, 2));
  };

  const buildConfigurationDetails = () => {
    const advanced = parseJsonInput(configAdvancedJson);
    const allowedDomains = configDomains
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const baseSteps: Array<Record<string, unknown>> = [];

    if (configStartUrl.trim()) {
      baseSteps.push({
        id: "step-1",
        name: "Open configured site",
        action: "goto",
        url: configStartUrl.trim(),
        verification: {
          urlIncludes:
            allowedDomains[0] ||
            (() => {
              try {
                return new URL(configStartUrl.trim()).hostname;
              } catch {
                return "";
              }
            })()
        }
      });
    }

    if (configVerifyText.trim()) {
      baseSteps.push({
        id: `step-${baseSteps.length + 1}`,
        name: "Verify configured page text",
        action: "extract",
        target: { text: configVerifyText.trim() },
        verification: { textVisible: configVerifyText.trim() }
      });
    }

    return {
      agentId: "dashboard-operator",
      allowedDomains,
      metadata: {
        description: configDescription.trim()
      },
      steps: baseSteps,
      ...advanced
    };
  };

  const launchJob = async () => {
    setLaunchError("");
    setLaunchSuccess("");
    try {
      const details = parseJsonInput(launchDetails);
      const response = await postJson<{ success: true; job: JobRecord }>("/api/jobs", {
        task: launchTask,
        details
      });
      setLaunchSuccess("Process created and queued.");
      setSelectedJobId(response.job.id);
      upsertJob(response.job);
      setLaunchTask("");
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
      const details = parseJsonInput(contextDetails);
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
      setSelectedJob(response.job);
      upsertJob(response.job);
    } catch (error) {
      setContextError(error instanceof Error ? error.message : "Failed to send context");
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

      if (!Array.isArray((details as { steps?: unknown[] }).steps) || ((details as { steps?: unknown[] }).steps || []).length === 0) {
        throw new Error("Provide at least a start URL or advanced JSON steps");
      }

      if (selectedConfigId) {
        await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:3200"}/api/configurations/${selectedConfigId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: configName,
            description: configDescription,
            task: configTask,
            details
          })
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

  const launchFromConfiguration = async (configId: string) => {
    setConfigError("");
    setConfigSuccess("");
    try {
      const response = await postJson<{ success: true; job: JobRecord }>(`/api/configurations/${configId}/launch`, {});
      upsertJob(response.job);
      setSelectedJobId(response.job.id);
      setActiveTab("monitor");
      setConfigSuccess("Configuration launched as a new process.");
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "Failed to launch configuration");
    }
  };

  return (
    <main className="at-shell">
      <header className="at-topbar">
        <div className="at-brand">
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
          <div>
            <div className="at-brand-title">AgentTrust</div>
            <div className="at-brand-subtitle">Identity &amp; Audit Layer for AI Agents</div>
          </div>
        </div>
        <div className="at-topbar-right">
          <div className="at-live-pill">
            <span className="at-live-dot" />
            Live
          </div>
          {metrics && (
            <div className="at-subtle text-sm">
              {metrics.totalJobs} jobs · {(metrics.successRate * 100).toFixed(0)}% success
            </div>
          )}
        </div>
      </header>

      <div className="at-page">
        <nav className="at-tabs">
          <button className={`at-tab ${activeTab === "monitor" ? "active" : ""}`} type="button" onClick={() => setActiveTab("monitor")}>Monitor</button>
          <button className={`at-tab ${activeTab === "jobs" ? "active" : ""}`} type="button" onClick={() => setActiveTab("jobs")}>Jobs</button>
          <button className={`at-tab ${activeTab === "approvals" ? "active" : ""}`} type="button" onClick={() => setActiveTab("approvals")}>Approvals</button>
          <button className={`at-tab ${activeTab === "metrics" ? "active" : ""}`} type="button" onClick={() => setActiveTab("metrics")}>Metrics</button>
          <button className={`at-tab ${activeTab === "configurations" ? "active" : ""}`} type="button" onClick={() => setActiveTab("configurations")}>Configurations</button>
        </nav>

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
                <span className="at-subtle text-xs">Friendly bot setup for non-technical users</span>
              </div>
              <div className="at-card-body space-y-4">
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
                  <label className="at-label">Advanced JSON details</label>
                  <textarea className="at-textarea" value={configAdvancedJson} onChange={(event) => setConfigAdvancedJson(event.target.value)} />
                  <div className="at-help">
                    Optional advanced settings. You can provide extra metadata or full step overrides here.
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

        {activeTab !== "configurations" && (
          <>
        <section className="at-card mt-3">
          <div className="at-card-header">
            <h2 className="at-card-title">Launch New Process</h2>
            <span className="at-subtle text-xs">Prompt the agent and attach structured JSON details</span>
          </div>
          <div className="at-card-body space-y-4">
            <div className="at-field">
              <label className="at-label" htmlFor="launch-task">Task prompt</label>
              <input
                id="launch-task"
                className="at-input"
                value={launchTask}
                onChange={(event) => setLaunchTask(event.target.value)}
                placeholder="Describe the process you want the agent to execute"
              />
            </div>
            <div className="at-field">
              <label className="at-label" htmlFor="launch-details">JSON details</label>
              <textarea
                id="launch-details"
                className="at-textarea"
                value={launchDetails}
                onChange={(event) => setLaunchDetails(event.target.value)}
              />
              <div className="at-help">
                Include `steps`, `allowedDomains`, `agentId`, and any `metadata` needed for reliable execution.
              </div>
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

        {metrics && (
          <section className="at-stats">
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

        <div className="at-grid mt-3 lg:grid-cols-[1.2fr_0.8fr]">
          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Agent Overview</h2>
              <span className="at-subtle text-xs">Live execution list</span>
            </div>
            <div className="at-card-body space-y-3">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  className={`at-job-button ${selectedJobId === job.id ? "active" : ""}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="at-code at-subtle">{job.id}</span>
                    <span className="at-status-badge">{job.status}</span>
                  </div>
                  <div className="mt-2 text-sm">Current step: {job.currentStep || "Queued"}</div>
                  <div className="at-progress">
                    <div className="at-progress-bar" style={{ width: `${job.progress || 0}%` }} />
                  </div>
                </button>
              ))}
              {jobs.length === 0 && <div className="at-subtle text-sm">No jobs yet.</div>}
            </div>
          </section>

          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Approval Inbox</h2>
              <span className="at-subtle text-xs">Step-up decisions</span>
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
        </div>

        <div className="at-grid mt-3 lg:grid-cols-[1fr_1fr]">
          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Live Execution View</h2>
              {selectedJob && (
                <div className="flex gap-2">
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
              )}
            </div>
            <div className="at-card-body">
            {selectedJob ? (
              <div className="space-y-3 text-sm">
                <div>Status: {selectedJob.status}</div>
                <div>Current step: {selectedJob.currentStep || "None"}</div>
                <div>Replay chunks captured: {replayCount}</div>
                {selectedJob.error && <div style={{ color: "var(--c-danger)" }}>Error: {selectedJob.error}</div>}
              </div>
            ) : (
              <div className="at-subtle text-sm">Select a job to inspect live execution.</div>
            )}
            </div>
          </section>

          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Prompt Selected Process</h2>
            </div>
            <div className="at-card-body">
            {selectedJob ? (
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
                    Use `appendSteps` to add new queued work. Other JSON details are stored alongside the operator prompt.
                  </div>
                </div>
                {contextError && <div className="at-error">{contextError}</div>}
                {contextSuccess && <div className="at-success">{contextSuccess}</div>}
                <div className="flex justify-end">
                  <button className="at-btn at-btn-primary" type="button" onClick={sendContext}>
                    Send Prompt
                  </button>
                </div>
              </div>
            ) : (
              <div className="at-subtle text-sm">Select a process to send additional prompt details.</div>
            )}
            </div>
          </section>
        </div>

        <div className="at-grid mt-3 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Step Timeline</h2>
            </div>
            <div className="at-card-body space-y-3">
              {selectedTimeline.map((step) => (
                <div key={step.id} className="at-step-card">
                  <div className="flex items-center justify-between">
                    <span>{step.sequence + 1}. {step.name}</span>
                    <span className="at-subtle text-xs uppercase">{step.status}</span>
                  </div>
                  <div className="at-subtle mt-1 text-xs">
                    Retries: {step.retryCount} | Failure: {step.failureType}
                  </div>
                  {step.failureMessage && <div className="mt-1 text-xs" style={{ color: "var(--c-danger)" }}>{step.failureMessage}</div>}
                </div>
              ))}
              {selectedTimeline.length === 0 && <div className="at-subtle text-sm">No steps yet.</div>}
            </div>
          </section>

          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Process Context &amp; Replay</h2>
            </div>
            <div className="at-card-body">
            {operatorPrompts.length > 0 && (
              <div className="space-y-2 pb-4">
                <div className="at-label">Operator prompts</div>
                {operatorPrompts.slice().reverse().slice(0, 4).map((entry, index) => (
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
              rrweb storage is wired through replay chunks. This panel is ready for `rrweb-player` hydration once the worker records full browser events for the selected job.
            </div>
            </div>
          </section>
        </div>

        <div className="at-grid mt-3 lg:grid-cols-[1fr]">
          <section className="at-card">
            <div className="at-card-header">
              <h2 className="at-card-title">Metrics Dashboard</h2>
            </div>
            <div className="at-card-body">
              {metrics ? (
                <div className="space-y-2 text-sm">
                  <div>Completed: {metrics.completedJobs}</div>
                  <div>Failed: {metrics.failedJobs}</div>
                  <div>Average execution: {Math.round(metrics.averageExecutionMs)} ms</div>
                  <div className="pt-2">Failure breakdown:</div>
                  {Object.entries(metrics.failureBreakdown).map(([key, value]) => (
                    <div key={key} className="flex justify-between" style={{ color: "var(--c-text-2)" }}>
                      <span>{key}</span>
                      <span>{value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="at-subtle text-sm">Loading metrics...</div>
              )}
            </div>
          </section>
        </div>
          </>
        )}
      </div>
    </main>
  );
}
