import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

// danger: 화면 위 삭제·취소 버튼(빨간 글자, 보조 버튼 모양). danger-solid: 확인 다이얼로그의 최종 삭제 버튼
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-solid';
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

// 포커스 링은 전역 :focus-visible(2px brand outline)이 그린다.
// html 글자 크기가 14px 이라 rem 단위(h-9 등)는 소수 px 이 되므로 높이·좌우 여백은 px 로 고정한다.
const base =
  'inline-flex items-center justify-center gap-1.5 rounded border font-semibold font-sans whitespace-nowrap ' +
  'transition-colors duration-fast ease-out disabled:pointer-events-none';

const sizes: Record<ButtonSize, string> = {
  sm: 'h-[30px] px-[10px] text-sm',
  md: 'h-[36px] px-[14px] text-md',
  lg: 'h-[44px] px-[20px] text-base',
};

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-white border-brand hover:bg-brand-hover hover:border-brand-hover active:bg-brand-pressed',
  secondary: 'bg-surface text-ink border-line-strong hover:bg-surface-hover',
  ghost: 'bg-transparent text-ink-muted border-transparent hover:bg-surface-hover hover:text-ink',
  danger: 'bg-surface text-danger border-line-strong hover:bg-danger-bg',
  'danger-solid': 'bg-danger text-white border-danger hover:bg-danger/90',
};

// 비활성은 흐린 보라가 아니라 회색. 로딩 중에는 원래 색을 유지한다.
const disabledLook = 'bg-surface-hover text-ink-disabled border-surface-hover';

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
      className={cn(
        base,
        sizes[size],
        disabled && !loading ? disabledLook : variants[variant],
        full && 'w-full',
        className,
      )}
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
