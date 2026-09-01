import type { Transition } from "framer-motion";

/** Apple 风格的生产动效令牌：普通界面无弹跳，动量交互才允许回弹。 */
export const EASE_OUT: [number, number, number, number] = [0.23, 1, 0.32, 1];

export const MOTION_INSTANT: Transition = { duration: 0 };
export const SPRING_CONTROL: Transition = {
  type: "spring",
  bounce: 0,
  duration: 0.24,
};
export const SPRING_PANEL: Transition = {
  type: "spring",
  bounce: 0,
  duration: 0.4,
};
export const SPRING_SHEET: Transition = {
  type: "spring",
  bounce: 0,
  duration: 0.45,
};

export const FADE_REDUCED: Transition = { duration: 0.12, ease: EASE_OUT };
export const FADE_FAST: Transition = { duration: 0.15, ease: EASE_OUT };
export const FADE_ENTER: Transition = { duration: 0.2, ease: EASE_OUT };
