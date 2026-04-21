'use client';

import { Children, type HTMLAttributes, type ReactNode } from 'react';
import { useRise } from './useRise';

export type RiseProps = HTMLAttributes<HTMLDivElement> & {
  delay?: number;
  y?: number;
  duration?: number;
};

export function Rise({
  delay = 0,
  y = 8,
  duration = 400,
  style,
  children,
  ...rest
}: RiseProps) {
  const { style: riseStyle } = useRise({ delay, y, duration });
  return (
    <div style={{ ...riseStyle, ...style }} {...rest}>
      {children}
    </div>
  );
}

export type StaggerProps = {
  children: ReactNode;
  baseDelay?: number;
  step?: number;
  y?: number;
  duration?: number;
};

/**
 * children 각각을 <Rise>로 감싸며 delay를 누적 증가.
 * 10개 이상이면 step을 40ms 이하로 줄이는 것을 권장 (motion.md).
 */
export function Stagger({
  children,
  baseDelay = 0,
  step = 60,
  y = 8,
  duration = 400,
}: StaggerProps) {
  return (
    <>
      {Children.map(children, (child, i) => (
        <Rise key={i} delay={baseDelay + i * step} y={y} duration={duration}>
          {child}
        </Rise>
      ))}
    </>
  );
}
