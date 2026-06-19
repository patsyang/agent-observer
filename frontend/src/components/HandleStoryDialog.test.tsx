import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { HandleStoryDialog } from './HandleStoryDialog';

describe('HandleStoryDialog', () => {
  it('enforces structured conclusion before submit and sends handling fields', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<HandleStoryDialog onCancel={() => {}} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole('button', { name: /^处理$/ }));
    expect(screen.getByRole('alert')).toHaveTextContent(/必须选择结构化结论/);
    expect(onSubmit).not.toHaveBeenCalled();

    await userEvent.selectOptions(screen.getByLabelText(/结论/), 'needs_fix');
    await userEvent.type(screen.getByLabelText(/备注/), 'Owner assigned');
    await userEvent.click(screen.getByRole('button', { name: /^处理$/ }));

    expect(onSubmit).toHaveBeenCalledWith({ conclusion_code: 'needs_fix', note: 'Owner assigned' });
    expect(await screen.findByText(/故事已处理/)).toBeInTheDocument();
  });
});
