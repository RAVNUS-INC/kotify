import type { SVGProps } from 'react';

export const ICON_PATHS = {
  home: 'M2 7l6-5 6 5v7a1 1 0 01-1 1H3a1 1 0 01-1-1V7z M6 15v-4h4v4',
  send: 'M14 2L7 9 M14 2l-4 12-3-5-5-3 12-4z',
  inbox: 'M2 9h4l1 2h2l1-2h4 M2 9l2-6h8l2 6v5a1 1 0 01-1 1H3a1 1 0 01-1-1V9z',
  users: 'M6 8a3 3 0 100-6 3 3 0 000 6zM1 14a5 5 0 0110 0 M11 3a3 3 0 010 6 M11 14h4',
  user: 'M8 8a3 3 0 100-6 3 3 0 000 6z M2 14a6 6 0 0112 0',
  user2: 'M8 8a3 3 0 100-6 3 3 0 000 6z M2 14a6 6 0 0112 0',
  settings:
    'M8 10a2 2 0 100-4 2 2 0 000 4z M13 8.7l1.3.7-1 1.7-1.4-.4a5.5 5.5 0 01-1.4.8L10 13H6l-.5-1.5a5.5 5.5 0 01-1.4-.8l-1.4.4-1-1.7 1.3-.7a5.5 5.5 0 010-1.4L1.7 6.6l1-1.7 1.4.4a5.5 5.5 0 011.4-.8L6 3h4l.5 1.5a5.5 5.5 0 011.4.8l1.4-.4 1 1.7-1.3.7a5.5 5.5 0 010 1.4z',
  clock: 'M8 4v4l3 2 M8 14A6 6 0 108 2a6 6 0 000 12z',
  calendar: 'M3 5h10v8H3zM3 7h10 M6 3v3 M10 3v3',
  bell: 'M4 11V7a4 4 0 118 0v4l1 1.5H3L4 11z M6.5 14a1.5 1.5 0 003 0',
  shield: 'M8 14s5-2.5 5-7V4L8 2 3 4v3c0 4.5 5 7 5 7z',
  key: 'M10 6a3 3 0 11-2.8 4H6v1H5v1H4v1H2v-2l5.2-5.2A3 3 0 0110 6z M10.5 5.5l.5.5',
  phone: 'M3 2h3l1 3-1.5 1a9 9 0 004.5 4.5L11 9l3 1v3a1 1 0 01-1 1A11 11 0 012 3a1 1 0 011-1z',
  message: 'M2 4h12v8H5l-3 2V4z',
  chat: 'M2 4h12v8H5l-3 2V4z',
  chart: 'M2 14h12 M4 11v-3 M8 11V6 M12 11V3',
  barChart: 'M3 14V8 M8 14V4 M13 14v-7',
  lineChart: 'M2 12l4-4 3 2 5-6 M14 4V3h-1',
  search: 'M7 12a5 5 0 100-10 5 5 0 000 10z M11 11l3 3',
  plus: 'M8 3v10 M3 8h10',
  minus: 'M3 8h10',
  x: 'M4 4l8 8 M12 4l-8 8',
  check: 'M3 8l3 3 7-7',
  chevronDown: 'M4 6l4 4 4-4',
  chevronRight: 'M6 4l4 4-4 4',
  chevronLeft: 'M10 4L6 8l4 4',
  chevronUp: 'M4 10l4-4 4 4',
  arrowRight: 'M3 8h10 M10 5l3 3-3 3',
  arrowLeft: 'M13 8H3 M6 5L3 8l3 3',
  arrowUp: 'M8 13V3 M5 6l3-3 3 3',
  arrowDown: 'M8 3v10 M5 10l3 3 3-3',
  external:
    'M9 3h4v4 M13 3L8 8 M13 9v3a1 1 0 01-1 1H4a1 1 0 01-1-1V4a1 1 0 011-1h3',
  download: 'M8 2v8 M4 7l4 4 4-4 M3 14h10',
  upload: 'M8 11V3 M4 6l4-4 4 4 M3 14h10',
  copy:
    'M5 5V3a1 1 0 011-1h7a1 1 0 011 1v7a1 1 0 01-1 1h-2 M2 6h7a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V7a1 1 0 011-1z',
  trash: 'M3 5h10 M5 5V3h6v2 M5 5l1 9h4l1-9 M7 8v4 M9 8v4',
  edit: 'M11 2l3 3-8 8H3v-3l8-8z M10 3l3 3',
  pencil: 'M11 2l3 3-8 8H3v-3l8-8z',
  filter: 'M2 3h12l-5 6v4l-2 1V9L2 3z',
  sort: 'M5 3v10 M3 11l2 2 2-2 M11 13V3 M9 5l2-2 2 2',
  more: 'M3 8a1 1 0 102 0 1 1 0 00-2 0z M7 8a1 1 0 102 0 1 1 0 00-2 0z M11 8a1 1 0 102 0 1 1 0 00-2 0z',
  moreV: 'M8 3a1 1 0 102 0 1 1 0 00-2 0z M8 7a1 1 0 102 0 1 1 0 00-2 0z M8 11a1 1 0 102 0 1 1 0 00-2 0z',
  menu: 'M2 4h12 M2 8h12 M2 12h12',
  info: 'M8 14A6 6 0 108 2a6 6 0 000 12z M8 7v4 M8 5h.01',
  help: 'M8 14A6 6 0 108 2a6 6 0 000 12z M6 6a2 2 0 114 0c0 1-2 1-2 3 M8 11h.01',
  alert: 'M8 2l6 11H2L8 2z M8 6v3 M8 11h.01',
  alertTri: 'M8 2l6 11H2L8 2z M8 6v3 M8 11h.01',
  warning: 'M8 2l6 11H2L8 2z M8 6v3 M8 11h.01',
  error: 'M8 14A6 6 0 108 2a6 6 0 000 12z M5 5l6 6 M11 5l-6 6',
  success: 'M8 14A6 6 0 108 2a6 6 0 000 12z M5 8l2 2 4-4',
  close: 'M4 4l8 8 M12 4l-8 8',
  link: 'M7 9a3 3 0 01-2 2L3 13a3 3 0 114-4 M9 7a3 3 0 012-2l2-2a3 3 0 11-4 4',
  linkIcon:
    'M7 9a3 3 0 01-2 2L3 13a3 3 0 114-4 M9 7a3 3 0 012-2l2-2a3 3 0 11-4 4',
  lock: 'M4 7h8v6H4zM6 7V5a2 2 0 114 0v2',
  unlock: 'M4 7h8v6H4zM6 7V5a2 2 0 014 0',
  eye: 'M8 4C4 4 2 8 2 8s2 4 6 4 6-4 6-4-2-4-6-4z M8 10a2 2 0 100-4 2 2 0 000 4z',
  eyeOff:
    'M2 2l12 12 M6 6a2 2 0 002 2 M4 5c-1 1-2 3-2 3s2 4 6 4c1 0 2-.2 2.5-.5 M9.5 9.5c.3-.5.5-1 .5-1.5a2 2 0 00-2-2c-.5 0-1 .2-1.5.5 M10 5.5c2 .5 4 2.5 4 2.5s-.7 1.2-2 2.2',
  at:
    'M8 12a4 4 0 110-8 4 4 0 010 8z M12 8v1a2 2 0 004 0v-1A7 7 0 008 1 7 7 0 001 8a7 7 0 0012 5',
  hash: 'M3 6h10 M3 10h10 M6 3l-2 10 M12 3l-2 10',
  star: 'M8 2l2 4.5 5 .5-3.5 3.5 1 5L8 13l-4.5 2.5 1-5L1 7l5-.5z',
  heart: 'M8 14s-5-3-5-7a3 3 0 015-2 3 3 0 015 2c0 4-5 7-5 7z',
  tag: 'M2 2h6l6 6-6 6-6-6V2z M5 5h.01',
  zap: 'M9 2L3 9h4l-1 5 6-7H8l1-5z',
  layers: 'M8 2l6 3-6 3-6-3 6-3z M2 8l6 3 6-3 M2 11l6 3 6-3',
  database:
    'M2 4c0-1 3-2 6-2s6 1 6 2-3 2-6 2-6-1-6-2z M2 4v4c0 1 3 2 6 2s6-1 6-2V4 M2 8v4c0 1 3 2 6 2s6-1 6-2V8',
  grid: 'M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z',
  list: 'M2 4h1 M6 4h8 M2 8h1 M6 8h8 M2 12h1 M6 12h8',
  table: 'M2 3h12v10H2z M2 7h12 M2 11h12 M6 3v10',
  refresh: 'M14 3v4h-4 M2 13v-4h4 M3 7a6 6 0 0110-2l1 2 M13 9a6 6 0 01-10 2l-1-2',
  play: 'M5 3l8 5-8 5V3z',
  pause: 'M5 3h3v10H5zM10 3h3v10h-3z',
  stop: 'M4 4h8v8H4z',
  forward: 'M3 3l5 5-5 5V3z M10 3l5 5-5 5V3z',
  logout:
    'M6 4V3a1 1 0 011-1h5a1 1 0 011 1v10a1 1 0 01-1 1H7a1 1 0 01-1-1v-1 M2 8h7 M6 5l-3 3 3 3',
  folder: 'M2 4h4l1 2h7v7H2V4z',
  file: 'M4 2h6l3 3v9H4V2z M10 2v3h3',
  fileText: 'M4 2h6l3 3v9H4V2z M10 2v3h3 M6 8h5 M6 10h5 M6 12h3',
  image: 'M2 3h12v10H2z M5 8l2 2 3-3 4 4 M5.5 6.5a1 1 0 100-2 1 1 0 000 2z',
  paperclip: 'M13 8l-6 6a3 3 0 11-4-4l7-7a2 2 0 013 3L6 13',
  circle: 'M8 14A6 6 0 108 2a6 6 0 000 12z',
  dot: 'M8 10a2 2 0 100-4 2 2 0 000 4z',
  square: 'M2 2h12v12H2z',
  bold: 'M4 2h4a3 3 0 012 5 3 3 0 01-2 5H4V2z M4 8h5',
  italic: 'M7 2h6 M3 14h6 M10 2L6 14',
  underline: 'M5 2v6a3 3 0 106 0V2 M4 14h8',
  globe: 'M8 14A6 6 0 108 2a6 6 0 000 12z M2 8h12 M8 2a9 9 0 010 12 M8 2a9 9 0 000 12',
  building: 'M3 14V3h8v11 M5 6h1 M5 9h1 M5 12h1 M9 6h1 M9 9h1 M9 12h1 M11 8h2v6h-2',
  shoppingBag: 'M3 5h10l-1 9H4L3 5z M6 5V3a2 2 0 014 0v2',
  creditCard: 'M2 4h12v8H2z M2 7h12',
  activity: 'M2 8h3l2-5 3 10 2-5h2',
  trending: 'M2 11l4-4 3 2 5-6 M14 4V3h-1 M9 3h4',
  pin: 'M8 2l3 3-1 1v3l2 2H4l2-2V6L5 5l3-3z M8 11v3',
  mic: 'M8 2a2 2 0 012 2v4a2 2 0 11-4 0V4a2 2 0 012-2z M4 8a4 4 0 008 0 M8 12v2',
  smile: 'M8 14A6 6 0 108 2a6 6 0 000 12z M6 9a2 2 0 004 0 M6 6h.01 M10 6h.01',
  briefcase: 'M2 5h12v9H2z M6 5V3h4v2 M2 9h12',
  spark: 'M8 2l1.5 5L14 8l-4.5 1L8 14l-1.5-5L2 8l4.5-1z',
  wifi: 'M2 6a10 10 0 0112 0 M4 9a6 6 0 018 0 M6 12a2 2 0 014 0',
  signal: 'M3 12v2 M6 9v5 M9 6v8 M12 3v11',
} as const satisfies Record<string, string>;

export type IconName = keyof typeof ICON_PATHS;

export type IconProps = Omit<SVGProps<SVGSVGElement>, 'name'> & {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  title?: string;
};

export function Icon({
  name,
  size = 14,
  strokeWidth = 1.6,
  title,
  className,
  ...rest
}: IconProps) {
  const d = ICON_PATHS[name];
  const a11y = title
    ? { role: 'img' as const, 'aria-label': title }
    : { 'aria-hidden': true };
  if (!d) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        {...a11y}
        {...rest}
      >
        <circle cx="8" cy="8" r="6" strokeDasharray="2 2" />
      </svg>
    );
  }
  const segments = d.split(' M');
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      {...a11y}
      {...rest}
    >
      {segments.map((seg, i) => (
        <path key={i} d={i === 0 ? seg : `M${seg}`} />
      ))}
    </svg>
  );
}
