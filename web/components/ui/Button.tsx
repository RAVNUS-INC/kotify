import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
  full?: boolean;
  type?: 'button' | 'submit' | 'reset';
};

const base =
  'inline-flex items-center justify-center gap-1.5 rounded font-medium font-sans whitespace-nowrap ' +
  'transition-colors duration-fast ease-out ' +
  'focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(59,0,139,0.12)] ' +
  'disabled:opacity-50 disabled:pointer-events-none';

const sizes: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-sm',
  md: 'h-9 px-3 text-md',
  lg: 'h-11 px-4 text-base',
};

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-white border border-brand hover:bg-brand-hover',
  secondary: 'bg-surface text-gray-10 border border-gray-4 hover:bg-gray-1',
  ghost: 'bg-transparent text-ink-muted hover:bg-gray-2 hover:text-ink',
  danger: 'bg-danger text-white border border-danger hover:opacity-90',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    icon,
    iconRight,
    loading = false,
    full = false,
    type = 'button',
    disabled,
    className,
    children,
    ...rest
  },
  ref,
) {
  const spinnerSize = size === 'sm' ? 12 : size === 'lg' ? 16 : 14;
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(base, sizes[size], variants[variant], full && 'w-full', className)}
      {...rest}
    >
      {loading ? (
        <Spinner size={spinnerSize} />
      ) : (
        icon && <span className="inline-flex shrink-0">{icon}</span>
      )}
      {children}
      {!loading && iconRight && <span className="inline-flex shrink-0">{iconRight}</span>}
    </button>
  );
});

function Spinner({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      style={{ animation: 'k-spin 0.7s linear infinite' }}
    >
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2" />
      <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
