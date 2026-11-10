/** The prefix the app is served under, `/` or one such as `/hone/` (vite `base`). */
export const BASE = import.meta.env.BASE_URL

/** An absolute app path such as `/api/state`, placed under the served prefix. */
export const url = (path: string) => BASE + path.replace(/^\//, '')
