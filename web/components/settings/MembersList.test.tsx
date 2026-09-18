import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { MembersList } from './MembersList';

describe('MembersList', () => {
  it('renders a sender member returned by the settings API', () => {
    render(
      <MembersList
        members={[
          {
            id: 'sender-member',
            email: 'sender@example.com',
            name: 'Test Sender',
            role: 'sender',
            active: true,
            invitedAt: '2026-09-18',
          },
        ]}
      />,
    );

    expect(screen.getByText('Test Sender')).toBeInTheDocument();
    expect(screen.getByText('Sender')).toBeInTheDocument();
    expect(screen.getByText('sender@example.com')).toBeInTheDocument();
  });
});
