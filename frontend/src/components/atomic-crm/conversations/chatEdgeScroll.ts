const EDGE_EPSILON_PX = 1;

type ScrollMetrics = {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
};

export const shouldTrapEdgeWheel = (
  scroller: ScrollMetrics,
  deltaY: number,
) => {
  if (deltaY === 0) return false;
  const maxScrollTop = Math.max(
    0,
    scroller.scrollHeight - scroller.clientHeight,
  );
  if (maxScrollTop <= EDGE_EPSILON_PX) return true;
  if (deltaY < 0) return scroller.scrollTop <= EDGE_EPSILON_PX;
  return scroller.scrollTop >= maxScrollTop - EDGE_EPSILON_PX;
};
