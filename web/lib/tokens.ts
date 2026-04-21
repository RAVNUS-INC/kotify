export const motion = {
  ease: {
    out: 'cubic-bezier(.22,.9,.3,1)',
    inOut: 'cubic-bezier(.4,0,.2,1)',
    in: 'cubic-bezier(.4,0,1,1)',
  },
  duration: {
    fast: 120,
    base: 200,
    slow: 400,
  },
} as const;

export type MotionEase = keyof typeof motion.ease;
export type MotionDuration = keyof typeof motion.duration;
