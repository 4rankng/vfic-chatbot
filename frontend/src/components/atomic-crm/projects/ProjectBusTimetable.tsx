import { memo, useEffect, useId, useState } from "react";
import { BusFront, ChevronLeft, ChevronRight } from "lucide-react";
import { Loading01 } from "@untitledui/icons";

import { Badge } from "@/components/base/badges/badges";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { Button } from "@/components/base/buttons/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "../kit";
import type { BusRoute, BusTimetableList } from "../types";
import { getProjectBusTimetable } from "./project-knowledge-service";

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
  const headingId = useId();
  const [pagination, setPagination] = useState({ projectId, page: 1 });
  const page = pagination.projectId === projectId ? pagination.page : 1;
  const setPage = (nextPage: number) =>
    setPagination({ projectId, page: nextPage });
  const [snapshot, setSnapshot] = useState<{
    projectId: string;
    data: BusTimetableList;
  } | null>(null);
  const timetable = snapshot?.projectId === projectId ? snapshot.data : null;
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const routes = timetable?.data ?? [];
  const total = timetable?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / BUS_ROUTE_PAGE_SIZE));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    getProjectBusTimetable(projectId, {
      page,
      perPage: BUS_ROUTE_PAGE_SIZE,
    })
      .then((res) => {
        if (!cancelled) setSnapshot({ projectId, data: res });
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, page, retry]);

  return (
    <section aria-labelledby={headingId} aria-busy={loading}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3
          id={headingId}
          className="inline-flex items-center gap-2 text-section-title font-semibold"
        >
          <BusFront className="size-4 text-muted-foreground" />
          Lịch xe đưa đón
        </h3>
        <div className="flex items-center gap-2">
          {loading ? (
            <span className="inline-flex items-center gap-1.5 text-body text-muted-foreground">
              <Loading01
                className="size-4 shrink-0 animate-spin text-primary"
                aria-hidden="true"
              />
              Đang tải…
            </span>
          ) : (
            <span className="text-body text-muted-foreground">
              {total} tuyến
            </span>
          )}
          {total > BUS_ROUTE_PAGE_SIZE && (
            <span className="text-helper text-muted-foreground">
              Trang {page}/{pageCount}
            </span>
          )}
          {total > BUS_ROUTE_PAGE_SIZE && (
            <div className="flex items-center gap-1">
              <ButtonUtility
                tooltip="Trang trước"
                className="uu-scope"
                size="sm"
                isDisabled={loading || page <= 1}
                onClick={() => setPage(Math.max(1, page - 1))}
                icon={ChevronLeft}
              />
              <ButtonUtility
                tooltip="Trang sau"
                className="uu-scope"
                size="sm"
                isDisabled={loading || page >= pageCount}
                onClick={() => setPage(Math.min(pageCount, page + 1))}
                icon={ChevronRight}
              />
            </div>
          )}
        </div>
      </div>
      {loadError ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/25 bg-destructive/5 p-3 text-body"
        >
          <p>Chưa tải được lịch xe đưa đón.</p>
          <Button
            className="uu-scope"
            color="secondary"
            size="sm"
            onClick={() => setRetry((value) => value + 1)}
          >
            Thử lại
          </Button>
        </div>
      ) : null}
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
      ) : !loadError && !loading ? (
        <EmptyState
          className="mt-3"
          icon={<BusFront className="size-6" aria-hidden="true" />}
          title="Lịch xe đưa đón"
          description="Chưa có lịch xe đưa đón được trích xuất cho dự án này."
        />
      ) : null}
    </section>
  );
};

const BusRouteCard = memo(({ route }: { route: BusRoute }) => (
  <div className="rounded-md border bg-muted/15 p-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-body font-semibold leading-5">
            {route.route_name}
          </h4>
          {route.route_no && (
            <Badge className="uu-scope" type="color" size="sm" color="gray">
              Tuyến {route.route_no}
            </Badge>
          )}
        </div>
        <div className="mt-1 text-helper text-muted-foreground">
          {shiftLabel(route.shift)} • {directionLabel(route.direction)}
        </div>
      </div>
      <Badge
        className="uu-scope shrink-0"
        type="pill-color"
        size="sm"
        color="gray"
      >
        {route.stops.length} điểm
      </Badge>
    </div>

    {route.stops.length > 0 ? (
      <div className="mt-3 flex flex-wrap gap-1.5">
        {route.stops.map((stop) => (
          <Badge
            key={stop.id}
            className="uu-scope max-w-full gap-1"
            type="color"
            size="sm"
            color="gray"
          >
            <span className="max-w-[180px] truncate font-medium">
              {stop.stop_name}
            </span>
            {stop.scheduled_time && (
              <span className="font-mono text-caption text-fg-quaternary">
                {stop.scheduled_time}
              </span>
            )}
          </Badge>
        ))}
      </div>
    ) : (
      <p
        role="status"
        className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-helper text-muted-foreground"
      >
        Chưa có điểm đón cho tuyến này.
      </p>
    )}
  </div>
));
BusRouteCard.displayName = "BusRouteCard";
