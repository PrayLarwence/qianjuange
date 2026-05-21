import { ref } from 'vue';
import { jobsApi, type JobStatus } from '@/services/api';

export interface UseJobOptions {
  intervalMs?: number;
  onProgress?: (job: JobStatus) => void;
}

export function useJob(opts: UseJobOptions = {}) {
  const interval = opts.intervalMs ?? 800;
  const job = ref<JobStatus | null>(null);
  const running = ref(false);
  let timer: number | null = null;
  let currentId: string | null = null;

  function clear() {
    if (timer !== null) { window.clearInterval(timer); timer = null; }
  }

  async function poll(jobId: string): Promise<JobStatus> {
    currentId = jobId;
    running.value = true;
    return new Promise((resolve, reject) => {
      timer = window.setInterval(async () => {
        if (currentId !== jobId) return;
        try {
          const j = await jobsApi.get(jobId);
          job.value = j;
          opts.onProgress?.(j);
          if (j.status === 'completed') {
            clear(); running.value = false; resolve(j);
          } else if (j.status === 'error' || j.status === 'cancelled') {
            clear(); running.value = false; reject(new Error(j.error || j.status));
          }
        } catch {
          // 网络瞬断，继续轮询
        }
      }, interval);
    });
  }

  async function cancel() {
    if (!currentId) return;
    try { await jobsApi.cancel(currentId); } catch { /* ignore */ }
    clear();
    running.value = false;
  }

  function reset() {
    clear();
    job.value = null;
    running.value = false;
    currentId = null;
  }

  return { job, running, poll, cancel, reset };
}
