// Design tokens are scoped to the card and inherit Home Assistant's theme.
export const tokens = `
  :host {
    --ff-ink: var(--primary-text-color, #17263d);
    --ff-muted: var(--secondary-text-color, #657789);
    --ff-canvas: var(--primary-background-color, #f4f7fb);
    --ff-surface: var(--card-background-color, #fff);
    --ff-border: var(--divider-color, #dce3e9);
    --ff-accent: #087e8b;
    --ff-accent-dark: #096a74;
    --ff-accent-soft: #dbf1f0;
    --ff-success: #11705d;
    --ff-warning: #de9b4b;
    --ff-focus: #46b6c2;
    --ff-radius-sm: 9px;
    --ff-radius-md: 13px;
    --ff-radius-lg: 18px;
    --ff-shadow: 0 3px 12px #12304a0a;
    --ff-space-1: 6px;
    --ff-space-2: 10px;
    --ff-space-3: 16px;
    --ff-space-4: 24px;
  }
`;
