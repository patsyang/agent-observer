import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { PerfFailureRow, PerfSummary, PerfTaskDetail, PerfTaskRow, PerfTasksResponse } from '../api/types.performance';
import { formatDuration } from '../utils/numberFormat';
import { PerformancePage } from './PerformancePage';

const emptySummary: PerfSummary = {
  window: '24h',
  bucket_size_minutes: 60,
  totals: {
    task_count: 0,
    llm_call_count: 0,
    tool_call_count: 0,
    success_count: 0,
    failure_count: 0,
    interrupted_count: 0,
    success_rate: null,
  },
  latency: {},
  sample_count: 0,
};

const sampleSummary: PerfSummary = {
  window: '24h',
  bucket_size_minutes: 60,
  totals: {
    task_count: 5,
    llm_call_count: 12,
    tool_call_count: 8,
    success_count: 10,
    failure_count: 2,
    interrupted_count: 0,
    success_rate: 0.8333,
  },
  latency: {
    llm_call: {
      sample_count: 12,
      duration_sample_count: 12,
      ttft_sample_count: 12,
      tps_sample_count: 12,
      success_count: 10,
      failure_count: 2,
      duration_avg_ms: 200,
      duration_p50_ms: 180,
      duration_p95_ms: 450,
      duration_p99_ms: 500,
      duration_min_ms: 80,
      duration_max_ms: 500,
      ttft_avg_ms: 50,
      ttft_p50_ms: 45,
      ttft_p95_ms: 120,
      tps_avg: 15.5,
      tps_max: 30.2,
    },
  },
  sample_count: 21,
};

const emptyTasks: PerfTasksResponse = {
  window: '24h',
  page: 1,
  page_size: 20,
  total: 0,
  tasks: [],
};

// R2-E4: 样本数 >= 20 时显示 TTFT P95 和 TPS max
const sufficientSummary: PerfSummary = {
  window: '24h',
  bucket_size_minutes: 60,
  totals: {
    task_count: 5,
    llm_call_count: 25,
    tool_call_count: 8,
    success_count: 23,
    failure_count: 2,
    interrupted_count: 0,
    success_rate: 0.92,
  },
  latency: {
    llm_call: {
      sample_count: 25,
      duration_sample_count: 25,
      ttft_sample_count: 25,
      tps_sample_count: 25,
      success_count: 23,
      failure_count: 2,
      duration_avg_ms: 200,
      duration_p50_ms: 180,
      duration_p95_ms: 450,
      duration_p99_ms: 500,
      duration_min_ms: 80,
      duration_max_ms: 500,
      ttft_avg_ms: 50,
      ttft_p50_ms: 45,
      ttft_p95_ms: 120,
      tps_avg: 15.5,
      tps_max: 30.2,
    },
  },
  sample_count: 33,
};

describe('PerformancePage', () => {
  it('renders summary metrics when data loaded', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(sampleSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByTestId('perf-summary-tasks')).toBeDefined();
    expect(screen.getByText('5')).toBeDefined();
    expect(screen.getByText('12')).toBeDefined();
    expect(screen.getByText('83.33%')).toBeDefined();
  });

  it('renders empty state when no data', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByText('当前窗口内没有任务记录。')).toBeDefined();
    expect(screen.getByText('当前窗口内没有失败记录。')).toBeDefined();
  });

  it('renders error state when summary fails', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockRejectedValue(new Error('network'))}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByText('性能数据不可用。请确认后端服务正常。')).toBeDefined();
  });

  // R2-E4: 验证延迟卡显示 TTFT P95 和 TPS max
  it('renders TTFT P95 and TPS max when sample_count >= 20', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(sufficientSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByText('TTFT P50 45ms / P95 120ms')).toBeDefined();
    expect(screen.getByText('TPS 均值 15.5 / 峰值 30.2')).toBeDefined();
  });

  // P1-1（审查 #2）：duration_sample_count=0 时显示"无 duration 数据"
  it('renders 无 duration 数据 hint when duration_sample_count is 0', async () => {
    const noDurationSummary: PerfSummary = {
      ...sufficientSummary,
      latency: {
        llm_call: {
          ...sufficientSummary.latency.llm_call,
          sample_count: 5,
          duration_sample_count: 0,
          duration_p50_ms: 0,
          duration_p95_ms: 0,
          duration_p99_ms: 0,
        },
      },
    };
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(noDurationSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByText('无 duration 数据，不计算百分位')).toBeDefined();
  });

  // R2-E3: 验证新增的窗口选项
  it('renders new window options 2h, today, week', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByText('2小时')).toBeDefined();
    expect(screen.getByText('今天')).toBeDefined();
    expect(screen.getByText('本周')).toBeDefined();
  });
});

// R2-E7: formatDuration 人性化时长显示
describe('formatDuration', () => {
  it('formats milliseconds', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(500)).toBe('500ms');
  });
  it('formats seconds', () => {
    expect(formatDuration(1500)).toBe('1.5s');
    expect(formatDuration(30000)).toBe('30.0s');
  });
  it('formats minutes', () => {
    expect(formatDuration(65000)).toBe('1m 5s');
    expect(formatDuration(1800000)).toBe('30m');
  });
  it('formats hours', () => {
    expect(formatDuration(3700000)).toBe('1h 1m');
  });
  // M5: 修复边界 bug——原实现 Math.round(seconds % 60) 在四舍五入进位时
  // 产生 "1m 60s" / "60s" / "59m 60s" 等非法显示
  it('handles boundary 119500ms without "1m 60s"', () => {
    // 旧实现: 119.5s → 1m + round(59.5) = 60s → "1m 60s"（非法）
    // M5: tenths=119.5 → totalSeconds=120 → 2m 0s → "2m"
    expect(formatDuration(119500)).toBe('2m');
  });
  it('handles boundary 59950ms without "60.0s"', () => {
    // 旧实现: 59.95s → round(59.95) = 60s → "60.0s"（非法秒数）
    // M5: tenths=60.0 → >= 60 → totalSeconds=60 → 1m 0s → "1m"
    expect(formatDuration(59950)).toBe('1m');
  });
  it('handles boundary 3599500ms without "59m 60s"', () => {
    // 旧实现: 3599.5s → 59m + round(59.5) = 60s → "59m 60s"（非法）
    // M5: tenths=3599.5 → totalSeconds=3600 → 60m → 1h 0m → "1h"
    expect(formatDuration(3599500)).toBe('1h');
  });
});

// M2: 截断标志警告横幅
describe('PerformancePage truncated warning', () => {
  it('renders truncated warning when truncated flag is true', async () => {
    const truncatedSummary: PerfSummary = { ...emptySummary, truncated: true };
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(truncatedSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByTestId('perf-truncated-warning')).toBeDefined();
  });
  it('does not render truncated warning when flag is absent', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    expect(await screen.findByTestId('perf-summary-tasks')).toBeDefined();
    expect(screen.queryByTestId('perf-truncated-warning')).toBeNull();
  });
});

// Slice 3: "查看会话" 跳转按钮
describe('PerformancePage open fact button', () => {
  const taskWithFact: PerfTaskRow = {
    trace_id: 'trace-1',
    started_at: '2026-07-19T00:00:00+00:00',
    ended_at: '2026-07-19T00:01:00+00:00',
    call_count: 3,
    llm_call_count: 2,
    tool_call_count: 1,
    success_count: 2,
    failure_count: 1,
    total_duration_ms: 5000,
    agent_type: 'codex',
    conversation_ref: 'conv-1',
    fact_id: 'fact-task-1',
    task_duration_ms: 5000,
    task_error: 'interrupted',
    task_status: 'error',
  };

  const failureWithFact: PerfFailureRow = {
    signal_id: 'sig-1',
    fact_id: 'fact-fail-1',
    trace_id: 'trace-1',
    span_type: 'llm_call',
    span_name: 'llm_call',
    tool_name: '',
    duration_ms: 1200,
    error: 'timeout',
    occurred_at: '2026-07-19T00:00:30+00:00',
    agent_type: 'codex',
    conversation_ref: 'conv-1',
  };

  const taskDetailWithFact: PerfTaskDetail = {
    trace_id: 'trace-1',
    task: null,
    spans: [
      {
        signal_id: 'sig-span-1',
        fact_id: 'fact-span-1',
        span_id: 'span-1',
        parent_span_id: '',
        span_type: 'llm_call',
        span_name: 'llm_call',
        duration_ms: 800,
        ttft_ms: 100,
        tps: 10,
        status: 'ok',
        error: '',
        model: 'gpt-4',
        tool_name: '',
        occurred_at: '2026-07-19T00:00:10+00:00',
      },
    ],
    agent_type: 'codex',
    conversation_ref: 'conv-1',
    started_at: '2026-07-19T00:00:00+00:00',
    ended_at: '2026-07-19T00:01:00+00:00',
    call_count: 1,
    task_status: 'ok',
    task_error: '',
    context_events: [],
  };

  it('renders 查看会话 button in failure row when onOpenFact provided', async () => {
    const onOpenFact = vi.fn();
    const user = userEvent.setup();
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [failureWithFact] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
        onOpenFact={onOpenFact}
      />
    );
    const btn = await screen.findByTestId('perf-failure-open-fact');
    await user.click(btn);
    expect(onOpenFact).toHaveBeenCalledWith('fact-fail-1');
  });

  it('renders 查看会话 button in task row when onOpenFact provided', async () => {
    const onOpenFact = vi.fn();
    const user = userEvent.setup();
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
        onOpenFact={onOpenFact}
      />
    );
    const btn = await screen.findByTestId('perf-task-open-fact');
    await user.click(btn);
    expect(onOpenFact).toHaveBeenCalledWith('fact-task-1');
  });

  it('renders 查看会话 button in span row when task detail open', async () => {
    const onOpenFact = vi.fn();
    const user = userEvent.setup();
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(taskDetailWithFact)}
        onOpenFact={onOpenFact}
      />
    );
    // 先点击 trace 链接打开任务详情抽屉
    const traceLink = await screen.findByTestId('perf-trace-link');
    await user.click(traceLink);
    // 等待抽屉中的 span 行的查看会话按钮出现
    const spanBtn = await screen.findByTestId('perf-span-open-fact');
    await user.click(spanBtn);
    expect(onOpenFact).toHaveBeenCalledWith('fact-span-1');
  });

  it('does not render 查看会话 buttons when onOpenFact absent', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [failureWithFact] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    await screen.findByTestId('perf-task-row');
    expect(screen.queryByTestId('perf-task-open-fact')).toBeNull();
    expect(screen.queryByTestId('perf-failure-open-fact')).toBeNull();
  });

  it('shows placeholder "-" when fact_id is empty', async () => {
    const taskNoFact: PerfTaskRow = { ...taskWithFact, fact_id: '' };
    const failureNoFact: PerfFailureRow = { ...failureWithFact, fact_id: '' };
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskNoFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [failureNoFact] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
        onOpenFact={vi.fn()}
      />
    );
    await screen.findByTestId('perf-task-row');
    await screen.findByTestId('perf-failure-row');
    // fact_id 为空时按钮不渲染
    expect(screen.queryByTestId('perf-task-open-fact')).toBeNull();
    expect(screen.queryByTestId('perf-failure-open-fact')).toBeNull();
  });

  // Slice 5: 区分"已中断"与"失败"——interrupted 不应显示为"失败"
  it('shows 已中断 label for interrupted task instead of 失败', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [failureWithFact] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    await screen.findByTestId('perf-task-row');
    // task_with_fact 的 task_error='interrupted'，状态应显示为"已中断"
    expect(screen.getByText('已中断')).toBeDefined();
    // 失败时间线的 error 是 'timeout'，应显示为"失败"
    expect(screen.getByText('失败')).toBeDefined();
  });

  // Slice 3: 任务详情抽屉显示 context_events
  it('renders context events section in task detail drawer', async () => {
    const onOpenFact = vi.fn();
    const user = userEvent.setup();
    const detailWithContext: PerfTaskDetail = {
      ...taskDetailWithFact,
      task: {
        signal_id: 'sig-task-1',
        fact_id: 'fact-task-1',
        span_id: 'task-1',
        parent_span_id: '',
        span_type: 'task',
        span_name: 'codex_turn',
        duration_ms: 5000,
        ttft_ms: 0,
        tps: 0,
        status: 'error',
        error: 'interrupted',
        model: '',
        tool_name: '',
        occurred_at: '2026-07-19T00:00:00+00:00',
      },
      task_status: 'error',
      task_error: 'interrupted',
      context_events: [
        {
          fact_id: 'fact-ctx-1',
          fact_type: 'risk',
          category: 'file_change',
          normalized_event_type: 'event_msg:patch_apply_end',
          severity: 'medium',
          summary: 'Agent 修改了 3 个工作区文件',
          occurred_at: '2026-07-19T00:00:30+00:00',
        },
      ],
    };
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(detailWithContext)}
        onOpenFact={onOpenFact}
      />
    );
    const traceLink = await screen.findByTestId('perf-trace-link');
    await user.click(traceLink);
    // 抽屉显示"会话期间关键事件"区块
    expect(await screen.findByTestId('perf-context-events')).toBeDefined();
    expect(screen.getByText(/Agent 修改了 3 个工作区文件/)).toBeDefined();
    // 点击 context event 的查看会话按钮
    const ctxBtn = screen.getByTestId('perf-context-open-fact');
    await user.click(ctxBtn);
    expect(onOpenFact).toHaveBeenCalledWith('fact-ctx-1');
  });

  // Slice 3: 中断任务在抽屉里显示解释提示
  it('shows interrupt explanation hint in task detail for interrupted task', async () => {
    const user = userEvent.setup();
    const detailInterrupted: PerfTaskDetail = {
      ...taskDetailWithFact,
      task: {
        signal_id: 'sig-task-1',
        fact_id: 'fact-task-1',
        span_id: 'task-1',
        parent_span_id: '',
        span_type: 'task',
        span_name: 'codex_turn',
        duration_ms: 145000,
        ttft_ms: 0,
        tps: 0,
        status: 'error',
        error: 'interrupted',
        model: '',
        tool_name: '',
        occurred_at: '2026-07-19T00:00:00+00:00',
      },
      task_status: 'error',
      task_error: 'interrupted',
      context_events: [],
    };
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(detailInterrupted)}
      />
    );
    const traceLink = await screen.findByTestId('perf-trace-link');
    await user.click(traceLink);
    // 错误显示可读化
    expect(await screen.findByText(/用户中断（任务未完成）/)).toBeDefined();
    // 显示中断解释提示
    expect(screen.getByText(/该任务被用户主动中断，并非系统错误/)).toBeDefined();
  });

  // Slice E: LLM 调用数为 0 时显示说明文字（解释为何为 0）
  it('shows explanation hint when llm_call_count is 0', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    const card = await screen.findByTestId('perf-summary-llm');
    // P1-2: =0 分支应直接回答"为什么是 0"
    expect(card.textContent).toContain('当前为 0');
    expect(card.textContent).toContain('codex 拆分了 llm_call span');
    expect(card.textContent).toContain('claude 暂未拆分');
    // 互斥：=0 时不应出现"模型请求次数"
    expect(card.textContent).not.toContain('模型请求次数');
  });

  // Slice E: LLM 调用数 > 0 时 hint 包含"模型请求次数"
  it('shows 模型请求次数 hint when llm_call_count > 0', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(sampleSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    const card = await screen.findByTestId('perf-summary-llm');
    expect(card.textContent).toContain('模型请求次数');
    expect(card.textContent).toContain('codex 已拆分 llm_call span');
    // 互斥：>0 时不应出现"当前为 0"
    expect(card.textContent).not.toContain('当前为 0');
  });

  // Slice C: 延迟分布卡 P50/P95/P99 行有 title 解释
  it('renders title tooltip on latency row metrics', async () => {
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(sufficientSummary)}
        loadTasks={vi.fn().mockResolvedValue(emptyTasks)}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(null)}
      />
    );
    await screen.findByTestId('perf-summary-tasks');
    const smalls = document.querySelectorAll('.perf-latency-grid small[title]');
    expect(smalls.length).toBeGreaterThan(0);
    const titles = Array.from(smalls).map((s) => s.getAttribute('title') || '');
    // P2-2: 完整文案匹配，避免 substring 漏检
    expect(titles).toContain('百分位延迟（nearest-rank）：P50=中位数，P95=95% 请求快于此值，P99=99% 请求快于此值。单位 ms。仅统计有耗时数据的样本（duration_ms>0），样本数≥20 才计算，否则显示 —。');
    expect(titles).toContain('TTFT（Time To First Token，首 token 延迟）：从请求发出到收到第一个 token 的耗时。单位 ms。codex 此值含 turn 内工具耗时，非纯 LLM TTFT。样本数≥20 才计算，否则显示 —。');
    expect(titles).toContain('TPS（Tokens Per Second，每秒 token 数）：生成速度。单位 tokens/s。当前采集器暂未采集此指标，显示 —。');
  });

  // Slice D: 任务详情抽屉 耗时/TTFT/TPS 列头有 title 解释
  it('renders title tooltip on 耗时/TTFT/TPS th in task detail drawer', async () => {
    const user = userEvent.setup();
    render(
      <PerformancePage
        loadSummary={vi.fn().mockResolvedValue(emptySummary)}
        loadTasks={vi.fn().mockResolvedValue({ ...emptyTasks, tasks: [taskWithFact], total: 1 })}
        loadFailures={vi.fn().mockResolvedValue({ failures: [] })}
        loadTaskDetail={vi.fn().mockResolvedValue(taskDetailWithFact)}
      />
    );
    const traceLink = await screen.findByTestId('perf-trace-link');
    await user.click(traceLink);
    await screen.findByTestId('perf-task-detail');
    const ths = document.querySelectorAll('.perf-detail-drawer th[title]');
    const titles = Array.from(ths).map((th) => th.getAttribute('title') || '');
    // P2-2: 完整文案匹配，覆盖"耗时"列 title
    expect(titles).toContain('Span 自身执行耗时（end - start）。单位 ms。');
    expect(titles).toContain('TTFT（Time To First Token，首 token 延迟）：从请求发出到收到第一个 token 的耗时。单位 ms。codex 此值含 turn 内工具耗时，非纯 LLM TTFT。仅 LLM 调用 span 有此指标，其他类型显示 —。');
    expect(titles).toContain('TPS（Tokens Per Second，每秒 token 数）：生成速度。单位 tokens/s。当前采集器暂未采集此指标，显示 —。');
  });
});