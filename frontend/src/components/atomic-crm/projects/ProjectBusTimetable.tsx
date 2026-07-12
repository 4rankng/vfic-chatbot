import { memo, useEffect, useState } from "react";
import { BusFront, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { BusRoute, BusTimetableList } from "../types";
import { getProjectBusTimetable } from "@/lib/vfic/knowledgeService";

const shiftLabel = (shift: string) =>
  (
    ({
      admin: "Hành chính",
      day: "Ca ngày",
      night: "Ca đêm",
    }) as Record<string, string>
  )[shift] ?? shift;

const directionLabel = (direction: string) =>
  (
    ({
      outbound: "Lượt đi",
      return: "Lượt về",
    }) as Record<string, string>
  )[direction] ?? direction;

const BUS_ROUTE_PAGE_SIZE = 6;

export const BusTimetableSection = ({ projectId }: { projectId: string }) => {
  const [page, setPage] = useState(1);
  const [timetable, setTimetable] = useState<BusTimetableList | null>(null);
  const [loading, setLoading] = useState(true);
  const routes = timetable?.data ?? [];
  const total = timetable?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / BUS_ROUTE_PAGE_SIZE));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectBusTimetable(projectId, {
      page,
      perPage: BUS_ROUTE_PAGE_SIZE,
    })
      .then((res) => {
        if (!cancelled) setTimetable(res);
      })
      .catch(() => {
        if (!cancelled) {
          setTimetable({
            data: [],
            total: 0,
            page,
            per_page: BUS_ROUTE_PAGE_SIZE,
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, page]);

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-2 text-base font-semibold">
          <BusFront className="size-4 text-muted-foreground" />
          Lịch xe đưa đón
        </h3>
        <div className="flex items-center gap-2">
          {loading ? (
            <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin text-primary" />
              Đang tải…
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">{total} tuyến</span>
          )}
          {total > BUS_ROUTE_PAGE_SIZE && (
            <span className="text-xs text-muted-foreground">
              Trang {page}/{pageCount}
            </span>
          )}
          {total > BUS_ROUTE_PAGE_SIZE && (
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8"
                disabled={loading || page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                aria-label="Trang trước"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8"
                disabled={loading || page >= pageCount}
                onClick={() =>
                  setPage((value) => Math.min(pageCount, value + 1))
                }
                aria-label="Trang sau"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
        </div>
      </div>
      {loading && !timetable ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : routes.length > 0 ? (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {routes.map((route) => (
            <BusRouteCard key={route.id} route={route} />
          ))}
        </div>
      ) : (
        <p
          role="status"
          className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm text-muted-foreground"
        >
          Chưa có lịch xe đưa đón được trích xuất cho dự án này.
        </p>
      )}
    </section>
  );
};

const BusRouteCard = memo(({ route }: { route: BusRoute }) => (
  <div className="rounded-md border bg-muted/15 p-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold leading-5">
            {route.route_name}
          </h4>
          {route.route_no && (
            <Badge
              variant="outline"
              className="h-5 rounded-md px-1.5 text-badge"
            >
              Tuyến {route.route_no}
            </Badge>
          )}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {shiftLabel(route.shift)} • {directionLabel(route.direction)}
        </div>
      </div>
      <Badge variant="secondary" className="shrink-0 text-badge">
        {route.stops.length} điểm
      </Badge>
    </div>

    {route.stops.length > 0 ? (
      <div className="mt-3 flex flex-wrap gap-1.5">
        {route.stops.map((stop) => (
          <span
            key={stop.id}
            className="inline-flex max-w-full items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs"
          >
            <span className="max-w-[180px] truncate font-medium">
              {stop.stop_name}
            </span>
            {stop.scheduled_time && (
              <span className="font-mono text-caption text-muted-foreground">
                {stop.scheduled_time}
              </span>
            )}
          </span>
        ))}
      </div>
    ) : (
      <p
        role="status"
        className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
      >
        Chưa có điểm đón cho tuyến này.
      </p>
    )}
  </div>
));
BusRouteCard.displayName = "BusRouteCard";
