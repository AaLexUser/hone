/** The run page is wide for its pipeline graph; every other page keeps the reading width. */
export const pageWidth = (pathname: string) => (/^\/runs\/[^/]+/.test(pathname) ? 'max-w-[1440px] min-[1800px]:max-w-[1680px]' : 'max-w-[1200px]')
