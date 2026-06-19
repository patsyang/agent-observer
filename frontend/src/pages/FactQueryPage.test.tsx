import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { FactDetail, FactsResponse } from '../api/types';
import { FactQueryPage } from './FactQueryPage';

const facts: FactsResponse = {
  total: 2,
  limit: 50,
  offset: 0,
  facts: [
    {
      fact_id: 'event-low-001',
      fact_type: 'unknown',
      category: 'uncategorized',
      quality: 'low',
      severity: 'low',
      summary: 'Low evidence fact remains queryable',
      occurred_at: '2026-06-18T10:01:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      source_event_type: 'message',
      source_label: 'Codex 会话 conv-hash-001',
      content_preview: 'Prompt: 请检查 Dashboard 为什么没有数据',
      raw_available: true,
      raw_status: '已上传原文'
    },
    {
      fact_id: 'event-error-001',
      fact_type: 'error',
      category: 'tool_failure',
      quality: 'high',
      severity: 'high',
      summary: 'Tool execution failed with raw signature',
      occurred_at: '2026-06-18T10:00:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      source_event_type: 'tool_result',
      source_label: 'Codex 会话 conv-hash-001',
      content_preview: '工具 shell_command，退出码 1',
      raw_available: false,
      raw_status: '仅结构化字段'
    }
  ]
};

const detail: FactDetail = {
  fact: facts.facts[0],
  evidence_projection: {
    projection_id: 'proj-event-low-001',
    fact_id: 'event-low-001',
    category: 'uncategorized',
    span: 'session:demo',
    raw_hash: 'hash-low-001',
    projection_json: { role: 'user', content_length: 18, prompt_text: '请检查 Dashboard 为什么没有数据' },
    upload_raw: true,
    raw_content: '{"payload":{"content":[{"text":"请检查 Dashboard 为什么没有数据"}]}}'
  },
  evidence_projections: [
    {
      projection_id: 'proj-event-low-001',
      fact_id: 'event-low-001',
      category: 'codex_prompt',
      span: 'session:demo',
      raw_hash: 'hash-low-001',
      projection_json: { role: 'user', content_length: 18, prompt_text: '请检查 Dashboard 为什么没有数据' },
      upload_raw: true,
      raw_content: '{"payload":{"content":[{"text":"请检查 Dashboard 为什么没有数据"}]}}'
    }
  ],
  source_refs: { conversation_ref: 'conv-hash-001' },
  source_specific_json: { codex_event_type: 'message' }
};

describe('FactQueryPage', () => {
  it('filters low evidence facts and drills into projection detail', async () => {
    const user = userEvent.setup();
    const loadFacts = vi.fn(async (filters) => {
      const filtered = (filters.quality === 'low' ? facts.facts.filter((fact) => fact.quality === 'low') : facts.facts).filter(
        (fact) => !filters.fact_type || filters.fact_type === 'all' || fact.fact_type === filters.fact_type
      );
      return { facts: filtered, total: filtered.length, limit: filters.limit, offset: filters.offset };
    });
    render(
      <FactQueryPage
        loadFacts={loadFacts}
        loadFactDetail={async () => detail}
      />
    );

    expect(await screen.findByText('事实查询')).toBeInTheDocument();
    expect(screen.getByText(/用于追溯故事的原始依据/)).toBeInTheDocument();
    expect(screen.getByText('事实总数')).toBeInTheDocument();
    expect(loadFacts).toHaveBeenCalledWith({
      quality: 'all',
      fact_type: 'all',
      source: 'all',
      window: '1h',
      include_health: false,
      limit: 50,
      offset: 0,
    });
    expect(screen.getByText('显示采集器自检与心跳')).toBeInTheDocument();
    expect(screen.getByText(/排查采集链路时打开/)).toBeInTheDocument();
    expect(screen.getAllByText('待补证').length).toBeGreaterThan(0);
    expect(screen.getByText('已进入故事')).toBeInTheDocument();
    expect(screen.getByText('真实内容')).toBeInTheDocument();
    expect(screen.queryByText('排查价值')).not.toBeInTheDocument();
    expect(screen.getByText('工具 shell_command，退出码 1')).toBeInTheDocument();
    expect(screen.getByText('未上传原文，可查看摘要和字段')).toBeInTheDocument();
    expect(screen.queryByText('仅结构化字段')).not.toBeInTheDocument();
    expect(screen.getByText('Tool execution failed with raw signature')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('质量'), 'low');
    await waitFor(() => {
      expect(screen.queryByText('Tool execution failed with raw signature')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Low evidence fact remains queryable')).toBeInTheDocument();
    expect(screen.getByText('Prompt: 请检查 Dashboard 为什么没有数据')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('类型'), 'unknown');
    expect(screen.getByText('Low evidence fact remains queryable')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '查看 event-low-001' }));
    expect(await screen.findByText(/第 1 条/)).toBeInTheDocument();
    expect(screen.getByText(/event-low-001/)).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Prompt: 请检查 Dashboard 为什么没有数据/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('hash-low-001')).toBeInTheDocument();
    expect(screen.getByText('证据详情')).toBeInTheDocument();
    expect(screen.getByText('原始 Prompt')).toBeInTheDocument();
    expect(screen.getByText('结构化字段')).toBeInTheDocument();
    expect(screen.getByText('消息角色')).toBeInTheDocument();
    expect(screen.getByText('Prompt 摘要')).toBeInTheDocument();
    expect(screen.getAllByText('消息事件').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Codex 会话 conv-hash-001').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/请检查 Dashboard 为什么没有数据/).length).toBeGreaterThan(0);
  });

  it('renders sensitive object projection as actionable detail', async () => {
    const riskFact = {
      fact_id: 'event-risk-001',
      fact_type: 'risk',
      category: 'sensitive_touch',
      quality: 'high' as const,
      severity: 'high',
      summary: 'Codex 会话触达敏感对象类别。',
      occurred_at: '2026-06-18T10:02:00+00:00',
      source: 'codex',
      promoted_to_story: true,
      source_event_type: 'function_call',
      source_label: 'Codex 会话 conv-risk-001',
      content_preview: '敏感对象触达: 凭据对象',
      raw_available: true,
      raw_status: '已上传原文'
    };
    const riskDetail: FactDetail = {
      fact: riskFact,
      evidence_projection: {
        projection_id: 'proj-event-risk-001',
        fact_id: 'event-risk-001',
        category: 'sensitive_touch',
        span: 'session:risk',
        raw_hash: 'hash-risk-sensitive-001',
        projection_json: { object_type: 'credential', category_count: 2, sensitive_categories: ['token', 'auth'] },
        upload_raw: true,
        raw_content: '{"payload":{"arguments":"git commit -m \\"token telemetry\\"; oh auth status"}}'
      },
      evidence_projections: [],
      source_refs: { conversation_ref: 'conv-risk-001' },
      source_specific_json: { codex_event_type: 'function_call' }
    };

    render(
      <FactQueryPage
        loadFacts={async () => ({ facts: [riskFact], total: 1, limit: 50, offset: 0 })}
        loadFactDetail={async () => riskDetail}
      />
    );

    await userEvent.click(await screen.findByRole('button', { name: '查看 event-risk-001' }));
    expect(await screen.findByText('敏感对象')).toBeInTheDocument();
    expect(screen.getAllByText('认证凭据对象').length).toBeGreaterThan(1);
    expect(screen.getByText('对象类型')).toBeInTheDocument();
    expect(screen.getByText('命中线索数')).toBeInTheDocument();
    expect(screen.getByText('token、auth')).toBeInTheDocument();
    expect(screen.getByLabelText('原文证据')).toHaveTextContent('token telemetry');
    const highlightedTerms = Array.from(document.querySelectorAll('mark.sensitive-hit')).map((node) => node.textContent);
    expect(highlightedTerms).toContain('auth');
    expect(highlightedTerms).not.toContain('token');
  });

  it('opens a fact passed from a story evidence link', async () => {
    const loadFactDetail = vi.fn(async () => detail);
    render(
      <FactQueryPage
        initialFactId="event-low-001"
        loadFacts={async () => facts}
        loadFactDetail={loadFactDetail}
      />
    );

    expect(await screen.findByText('证据详情')).toBeInTheDocument();
    expect(loadFactDetail).toHaveBeenCalledWith('event-low-001');
    expect(screen.getByText('原始 Prompt')).toBeInTheDocument();
  });

  it('shows story-linked fact detail even when the current list filter is empty', async () => {
    const loadFactDetail = vi.fn(async () => detail);
    render(
      <FactQueryPage
        initialFactId="event-low-001"
        loadFacts={async () => ({ facts: [], total: 0, limit: 50, offset: 0 })}
        loadFactDetail={loadFactDetail}
      />
    );

    expect(await screen.findByText('证据详情')).toBeInTheDocument();
    expect(screen.getByText(/当前筛选没有命中列表/)).toBeInTheDocument();
    expect(screen.getByText('原始 Prompt')).toBeInTheDocument();
  });

  it('paginates facts and keeps selected fact after refresh', async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 55 }, (_, index) => ({
      fact_id: `fact-${index + 1}`,
      fact_type: 'content',
      category: 'codex_prompt',
      quality: 'high' as const,
      severity: 'low',
      summary: `Prompt ${index + 1}`,
      occurred_at: '2026-06-18T10:00:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      content_preview: `Prompt: 第 ${index + 1} 条`,
      raw_available: false,
      raw_status: '仅结构化字段'
    }));
    const loadFacts = vi.fn(async (filters) => ({
      facts: rows.slice(filters.offset, filters.offset + filters.limit),
      total: rows.length,
      limit: filters.limit,
      offset: filters.offset,
    }));
    const loadFactDetail = vi.fn(async (factId: string) => ({
      ...detail,
      fact: rows.find((row) => row.fact_id === factId) ?? rows[0],
      evidence_projection: { ...detail.evidence_projection, fact_id: factId },
    }));

    render(<FactQueryPage loadFacts={loadFacts} loadFactDetail={loadFactDetail} />);

    expect(await screen.findByText(/共 55 条/)).toBeInTheDocument();
    expect(screen.getByText(/第\s*1\s*-\s*50\s*条/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => expect(loadFacts).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 50 })));
    expect(await screen.findByText(/第\s*51\s*-\s*55\s*条/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '查看 fact-51' }));
    const detailPanel = await screen.findByLabelText('证据详情');
    expect(within(detailPanel).getByText(/第 51 条/)).toHaveTextContent('fact-51');
    await user.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(loadFactDetail).toHaveBeenLastCalledWith('fact-51'));
    expect(screen.getByText(/最后刷新/)).toBeInTheDocument();
  });
});
