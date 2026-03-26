"use client";

import { create } from "zustand";

type AgentRecord = {
  id: string;
  status: string;
  progress?: number;
  currentStep?: string | null;
  error?: string | null;
};

type ApprovalRecord = {
  id: string;
  action: string;
  policyReason?: string | null;
  jobId: string;
};

type Store = {
  jobs: AgentRecord[];
  approvals: ApprovalRecord[];
  selectedJobId?: string;
  setJobs: (jobs: AgentRecord[]) => void;
  upsertJob: (job: AgentRecord) => void;
  setApprovals: (approvals: ApprovalRecord[]) => void;
  setSelectedJobId: (jobId?: string) => void;
};

export const useAgentsStore = create<Store>((set) => ({
  jobs: [],
  approvals: [],
  selectedJobId: undefined,
  setJobs: (jobs) => set({ jobs }),
  upsertJob: (job) =>
    set((state) => ({
      jobs: state.jobs.some((entry) => entry.id === job.id)
        ? state.jobs.map((entry) => (entry.id === job.id ? { ...entry, ...job } : entry))
        : [job, ...state.jobs]
    })),
  setApprovals: (approvals) => set({ approvals }),
  setSelectedJobId: (selectedJobId) => set({ selectedJobId })
}));
