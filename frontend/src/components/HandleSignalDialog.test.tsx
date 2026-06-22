import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { HandleSignalDialog } from './HandleSignalDialog';

describe('HandleSignalDialog', () => {
  it('submits structured conclusion', async () => {
    const onSubmit = vi.fn(async () => {});
    render(<HandleSignalDialog onCancel={() => {}} onSubmit={onSubmit} />);

    await userEvent.selectOptions(screen.getByLabelText('结论'), 'needs_fix');
    await userEvent.type(screen.getByLabelText('备注'), '需要修复工具参数');
    await userEvent.click(screen.getByRole('button', { name: '保存' }));

    expect(onSubmit).toHaveBeenCalledWith({ conclusion_code: 'needs_fix', note: '需要修复工具参数' });
  });
});

