begin;

create or replace function public.normalize_bus_route_key(p_name text)
returns text
language plpgsql
immutable
set search_path = public, extensions
as $$
declare
  v text := public.normalize_search_text(coalesce(p_name, ''));
begin
  v := regexp_replace(v, '\s+', ' ', 'g');
  v := btrim(v);

  if v = '' then
    return '';
  end if;

  if v in ('ktx cd bac bo', 'ktx cao dang bac bo') then
    return 'ktx cao dang bac bo';
  end if;

  if v = 'cau rao 1' then
    return 'cau rao';
  end if;

  if v = 'tl cau dam' then
    return 'tien lang cau dam';
  end if;

  if v = 'tl hung thang' then
    return 'tien lang hung thang';
  end if;

  return v;
end;
$$;

alter table public.bus_routes
  add column if not exists route_group_key text;

update public.bus_routes
set route_group_key = public.normalize_bus_route_key(route_name)
where route_group_key is null
   or route_group_key = '';

alter table public.bus_routes
  alter column route_group_key set not null;

create index if not exists bus_routes_group_key_idx
  on public.bus_routes (company_id, route_group_key, shift, direction);

create table if not exists public.bus_route_service_days (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  knowledge_source_id uuid references public.knowledge_sources(id) on delete cascade,
  route_group_key text not null,
  route_group_name text not null,
  day_group text not null check (day_group in ('mon_thu', 'fri', 'sat', 'sun')),
  day_label text not null,
  service_type text not null check (
    service_type in (
      'outbound_admin_and_day',
      'return_night',
      'return_admin',
      'outbound_night',
      'return_day'
    )
  ),
  availability_code text not null check (availability_code in ('A', 'M', 'X')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists bus_route_service_days_company_route_day_service_key
  on public.bus_route_service_days (company_id, route_group_key, day_group, service_type);

create index if not exists bus_route_service_days_project_route_day_idx
  on public.bus_route_service_days (project_id, route_group_key, day_group);

drop function if exists public.search_bus_timetable(text, text, text, text, text, integer);

create or replace function public.rebuild_bus_timetable_from_documents(
  p_project_slug text default 'vfic',
  p_company_name text default 'LG Display',
  p_source_name text default 'LGDisplay.txt',
  p_source_ref text default null,
  p_version text default '',
  p_source_type text default 'text'
)
returns table(routes_rebuilt integer, stops_rebuilt integer)
language plpgsql
set search_path = public, extensions
as $function$
declare
  v_project_id uuid;
  v_company_id uuid;
  v_source_id uuid;
  rec record;
  line_text text;
  stop_part text;
  stop_idx integer;
  header_match text[];
  route_match text[];
  day_match text[];
  weekly_route_match text[];
  flag text;
  flag_match text[];
  current_route_no text := null;
  current_route_name text := null;
  current_area text := null;
  current_mode text := null;
  current_page text := null;
  current_shift text := null;
  current_section text := null;
  current_weekly_route_name text := null;
  current_weekly_route_key text := null;
  pending_notes text := null;
  current_admin_block text := null;
  v_route_id uuid;
  stop_name_value text;
  stop_time_value time;
  v_day_group text;
begin
  insert into public.projects (slug, name)
  values (p_project_slug, upper(p_project_slug))
  on conflict (slug) do update set name = excluded.name
  returning id into v_project_id;

  insert into public.companies (project_id, name, aliases)
  values (
    v_project_id,
    p_company_name,
    case
      when lower(p_company_name) = lower('LG Display')
        then array['LGD', 'LG Display Việt Nam', 'LG Display Vietnam']
      else array[p_company_name]
    end
  )
  on conflict (project_id, name) do update
    set aliases = excluded.aliases
  returning id into v_company_id;

  insert into public.knowledge_sources (
    project_id,
    company_id,
    source_name,
    source_type,
    document_type,
    source_ref,
    version,
    status,
    metadata
  )
  values (
    v_project_id,
    v_company_id,
    p_source_name,
    p_source_type,
    'bus_schedule',
    p_source_ref,
    coalesce(p_version, ''),
    'published',
    jsonb_build_object('file_name', p_source_name, 'rebuilt_at', now())
  )
  on conflict (project_id, company_id, source_name, document_type, version) do update
  set source_ref = excluded.source_ref,
      source_type = excluded.source_type,
      status = excluded.status,
      metadata = excluded.metadata,
      updated_at = now()
  returning id into v_source_id;

  delete from public.bus_stops
  where route_id in (
    select br.id
    from public.bus_routes br
    join public.knowledge_sources ks on ks.id = br.knowledge_source_id
    where ks.company_id = v_company_id
      and ks.source_name = p_source_name
      and ks.document_type = 'bus_schedule'
  );

  delete from public.bus_routes br
  using public.knowledge_sources ks
  where ks.id = br.knowledge_source_id
    and ks.company_id = v_company_id
    and ks.source_name = p_source_name
    and ks.document_type = 'bus_schedule';

  delete from public.bus_route_service_days bsd
  using public.knowledge_sources ks
  where ks.id = bsd.knowledge_source_id
    and ks.company_id = v_company_id
    and ks.source_name = p_source_name
    and ks.document_type = 'bus_schedule';

  for rec in
    select d.id as document_id, line.line_no, line.text as line_text
    from public.documents d
    cross join lateral regexp_split_to_table(d.content, E'\n') with ordinality as line(text, line_no)
    where d.metadata ->> 'file_name' = p_source_name
    order by coalesce((d.metadata #>> '{loc,lines,from}')::int, 0), d.id, line.line_no
  loop
    line_text := btrim(rec.line_text);

    if line_text = '' then
      continue;
    end if;

    if line_text like '## 1. Bảng hoạt động theo tuần%' then
      current_section := 'weekly';
      current_weekly_route_name := null;
      current_weekly_route_key := null;
      continue;
    end if;

    if line_text like '## 2. Ca ngày%' then
      current_section := 'routes';
      current_shift := 'day';
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 3. Ca hành chính%' then
      current_section := 'admin';
      current_shift := 'admin';
      current_admin_block := null;
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 4. Ca đêm%' then
      current_section := 'routes';
      current_shift := 'night';
      current_route_name := null;
      pending_notes := null;
      continue;
    end if;

    if line_text like '## 5. Mục cần giữ nguyên%' then
      current_section := 'done';
      continue;
    end if;

    if current_section = 'weekly' then
      weekly_route_match := regexp_match(line_text, '^\d+\.\s+(.+)$');
      if weekly_route_match is not null then
        current_weekly_route_name := trim(weekly_route_match[1]);
        current_weekly_route_key := public.normalize_bus_route_key(current_weekly_route_name);
        continue;
      end if;

      day_match := regexp_match(
        line_text,
        '^-?\s*(Thứ Hai đến Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật):\s+(.+)$'
      );

      if day_match is not null and current_weekly_route_key is not null then
        v_day_group := case day_match[1]
          when 'Thứ Hai đến Thứ Năm' then 'mon_thu'
          when 'Thứ Sáu' then 'fri'
          when 'Thứ Bảy' then 'sat'
          when 'Chủ Nhật' then 'sun'
          else null
        end;

        foreach flag in array regexp_split_to_array(day_match[2], '\s*,\s*')
        loop
          flag_match := regexp_match(flag, '^\s*([a-z_]+)\s*=\s*([AMX])\s*$');
          if flag_match is null then
            continue;
          end if;

          insert into public.bus_route_service_days (
            project_id,
            company_id,
            knowledge_source_id,
            route_group_key,
            route_group_name,
            day_group,
            day_label,
            service_type,
            availability_code,
            metadata
          )
          values (
            v_project_id,
            v_company_id,
            v_source_id,
            current_weekly_route_key,
            current_weekly_route_name,
            v_day_group,
            day_match[1],
            flag_match[1],
            flag_match[2],
            jsonb_build_object('parsed_from', 'weekly_matrix')
          )
          on conflict (company_id, route_group_key, day_group, service_type) do update
          set project_id = excluded.project_id,
              knowledge_source_id = excluded.knowledge_source_id,
              route_group_name = excluded.route_group_name,
              day_label = excluded.day_label,
              availability_code = excluded.availability_code,
              metadata = excluded.metadata;
        end loop;
      end if;

      continue;
    end if;

    if current_section = 'routes' then
      header_match := regexp_match(
        line_text,
        '^### Tuyến\s+([^:]+):\s+([^|\n]+)\s+\|\s+Khu vực:\s+([^|\n]+)\s+\|\s+Chế độ:\s+([^|\n]+)\s+\|\s+Trang\s+(\d+)'
      );

      if header_match is not null then
        current_route_no := trim(header_match[1]);
        current_route_name := trim(header_match[2]);
        current_area := trim(header_match[3]);
        current_mode := trim(header_match[4]);
        current_page := trim(header_match[5]);
        pending_notes := null;
        continue;
      end if;

      if line_text ~ '^(Ghi chú|Điều kiện):' then
        pending_notes := concat_ws(E'\n', pending_notes, line_text);
        continue;
      end if;

      route_match := regexp_match(line_text, '^- Lộ trình\s+([^:]+):\s+(.+)$');

      if route_match is not null and current_route_name is not null then
        insert into public.bus_routes (
          project_id,
          company_id,
          knowledge_source_id,
          route_name,
          route_no,
          route_variant,
          route_group_key,
          shift,
          direction,
          area,
          mode,
          source_page,
          notes,
          metadata
        )
        values (
          v_project_id,
          v_company_id,
          v_source_id,
          current_route_name,
          current_route_no,
          trim(route_match[1]),
          public.normalize_bus_route_key(current_route_name),
          current_shift,
          'outbound',
          current_area,
          current_mode,
          current_page,
          pending_notes,
          jsonb_build_object('route_text', trim(route_match[2]))
        )
        on conflict (company_id, route_name, route_variant, shift, direction, source_page, mode) do update
        set route_no = excluded.route_no,
            route_group_key = excluded.route_group_key,
            area = excluded.area,
            notes = excluded.notes,
            metadata = excluded.metadata,
            knowledge_source_id = excluded.knowledge_source_id
        returning id into v_route_id;

        stop_idx := 0;
        foreach stop_part in array regexp_split_to_array(trim(route_match[2]), '\s*->\s*')
        loop
          stop_idx := stop_idx + 1;
          stop_name_value := trim(regexp_replace(stop_part, '@\d{2}:\d{2}$', ''));
          stop_time_value := null;

          if stop_part ~ '@\d{2}:\d{2}$' then
            stop_time_value := substring(stop_part from '@(\d{2}:\d{2})$')::time;
          end if;

          insert into public.bus_stops (
            route_id,
            stop_order,
            stop_name,
            stop_aliases,
            scheduled_time,
            raw_stop_text
          )
          values (
            v_route_id,
            stop_idx,
            stop_name_value,
            array_remove(array[
              stop_name_value,
              case when stop_name_value ilike '%Kiến An%' then 'Kiến An' end,
              case when stop_name_value ilike '%Quán Toan%' then 'Quán Toan' end,
              case when stop_name_value ilike '%An Dương%' then 'An Dương' end,
              case when stop_name_value ilike '%Đồ Sơn%' then 'Đồ Sơn' end,
              case when stop_name_value ilike '%An Lão%' then 'An Lão' end,
              case when stop_name_value ilike '%Kiến Thụy%' then 'Kiến Thụy' end,
              case when stop_name_value ilike '%Vĩnh Bảo%' then 'Vĩnh Bảo' end,
              case when stop_name_value ilike '%Thái Bình%' then 'Thái Bình' end,
              case when stop_name_value ilike '%Hải Dương%' then 'Hải Dương' end,
              case when stop_name_value ilike '%Quảng Yên%' then 'Quảng Yên' end
            ], null),
            stop_time_value,
            trim(stop_part)
          )
          on conflict (route_id, stop_order) do update
          set stop_name = excluded.stop_name,
              stop_aliases = excluded.stop_aliases,
              scheduled_time = excluded.scheduled_time,
              raw_stop_text = excluded.raw_stop_text;
        end loop;

        pending_notes := null;
      end if;

      continue;
    end if;

    if current_section = 'admin' then
      if line_text like '### Lượt đi tuyến Hà Nội%' then
        current_admin_block := 'hanoi_outbound';
        pending_notes := null;
        continue;
      end if;

      if line_text ~ '^- Ghi chú' then
        pending_notes := concat_ws(E'\n', pending_notes, regexp_replace(line_text, '^- ', ''));
        continue;
      end if;

      if current_admin_block = 'hanoi_outbound' and line_text ~ '^- .*@\d{2}:\d{2}.*LGD' then
        insert into public.bus_routes (
          project_id,
          company_id,
          knowledge_source_id,
          route_name,
          route_no,
          route_variant,
          route_group_key,
          shift,
          direction,
          area,
          mode,
          source_page,
          notes,
          metadata
        )
        values (
          v_project_id,
          v_company_id,
          v_source_id,
          'Hà Nội',
          '18',
          '1',
          public.normalize_bus_route_key('Hà Nội'),
          'admin',
          'outbound',
          'Hà Nội',
          'standard',
          '6',
          pending_notes,
          jsonb_build_object('route_text', regexp_replace(line_text, '^- ', ''))
        )
        on conflict (company_id, route_name, route_variant, shift, direction, source_page, mode) do update
        set route_group_key = excluded.route_group_key,
            notes = excluded.notes,
            metadata = excluded.metadata,
            knowledge_source_id = excluded.knowledge_source_id
        returning id into v_route_id;

        stop_idx := 0;
        foreach stop_part in array regexp_split_to_array(regexp_replace(line_text, '^- ', ''), '\s*->\s*')
        loop
          stop_idx := stop_idx + 1;
          stop_name_value := trim(regexp_replace(stop_part, '@\d{2}:\d{2}$', ''));
          stop_time_value := null;

          if stop_part ~ '@\d{2}:\d{2}$' then
            stop_time_value := substring(stop_part from '@(\d{2}:\d{2})$')::time;
          end if;

          insert into public.bus_stops (
            route_id,
            stop_order,
            stop_name,
            stop_aliases,
            scheduled_time,
            raw_stop_text
          )
          values (
            v_route_id,
            stop_idx,
            stop_name_value,
            array_remove(array[
              stop_name_value,
              case when stop_name_value ilike '%Hà Nội%' then 'Hà Nội' end,
              case when stop_name_value ilike '%Gia Lâm%' then 'Gia Lâm' end
            ], null),
            stop_time_value,
            trim(stop_part)
          )
          on conflict (route_id, stop_order) do update
          set stop_name = excluded.stop_name,
              stop_aliases = excluded.stop_aliases,
              scheduled_time = excluded.scheduled_time,
              raw_stop_text = excluded.raw_stop_text;
        end loop;

        pending_notes := null;
      end if;
    end if;
  end loop;

  update public.bus_routes
  set route_group_key = public.normalize_bus_route_key(route_name)
  where company_id = v_company_id
    and (route_group_key is null or route_group_key = '');

  return query
  select
    (
      select count(*)::integer
      from public.bus_routes
      where knowledge_source_id = v_source_id
    ),
    (
      select count(*)::integer
      from public.bus_stops bs
      join public.bus_routes br on br.id = bs.route_id
      where br.knowledge_source_id = v_source_id
    );
end;
$function$;

create or replace function public.search_bus_timetable(
  p_project_slug text default 'vfic',
  p_company_query text default 'LG Display',
  p_question text default '',
  p_shift text default null,
  p_location text default null,
  p_limit integer default 20
)
returns table(
  company_name text,
  route_name text,
  route_variant text,
  shift text,
  direction text,
  stop_order integer,
  stop_name text,
  scheduled_time text,
  area text,
  mode text,
  source_name text,
  source_page text,
  match_reason text,
  requested_day_group text,
  requested_day_label text,
  availability_code text
)
language sql
stable
set search_path = public, extensions
as $function$
  with params as (
    select
      public.normalize_search_text(coalesce(p_question, '')) as q,
      public.normalize_search_text(coalesce(p_location, '')) as loc,
      case
        when p_shift in ('day', 'night', 'admin') then p_shift
        when public.normalize_search_text(coalesce(p_question, '')) like '%ca dem%' then 'night'
        when public.normalize_search_text(coalesce(p_question, '')) like '%ca ngay%' then 'day'
        when public.normalize_search_text(coalesce(p_question, '')) like '%hanh chinh%' then 'admin'
        else null
      end as wanted_shift,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 6|t6|friday) ' then 'fri'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 7|t7|saturday) ' then 'sat'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (chu nhat|cn|sunday) ' then 'sun'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 2|t2|thu 3|t3|thu 4|t4|thu 5|t5|monday|tuesday|wednesday|thursday) ' then 'mon_thu'
        else null
      end as wanted_day_group,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 6|t6|friday) ' then 'Thứ Sáu'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 7|t7|saturday) ' then 'Thứ Bảy'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (chu nhat|cn|sunday) ' then 'Chủ Nhật'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 2|t2|monday) ' then 'Thứ Hai'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 3|t3|tuesday) ' then 'Thứ Ba'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 4|t4|wednesday) ' then 'Thứ Tư'
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (thu 5|t5|thursday) ' then 'Thứ Năm'
        else null
      end as wanted_day_label,
      case
        when (' ' || public.normalize_search_text(coalesce(p_question, '')) || ' ') ~ ' (ve|ve nha|roi lgd|tu lgd|sau ca) ' then 'return'
        else 'outbound'
      end as wanted_direction
  ),
  base as (
    select
      c.name as company_name,
      br.route_name,
      br.route_variant,
      br.shift,
      br.direction,
      bs.stop_order,
      bs.stop_name,
      bs.stop_aliases,
      to_char(bs.scheduled_time, 'HH24:MI') as scheduled_time,
      br.area,
      br.mode,
      ks.source_name,
      br.source_page,
      br.route_group_key,
      case
        when br.direction = 'outbound' and br.shift in ('day', 'admin') then 'outbound_admin_and_day'
        when br.direction = 'outbound' and br.shift = 'night' then 'outbound_night'
        when br.direction = 'return' and br.shift = 'night' then 'return_night'
        when br.direction = 'return' and br.shift = 'admin' then 'return_admin'
        when br.direction = 'return' and br.shift = 'day' then 'return_day'
        else null
      end as route_service_type,
      cal.availability_code,
      cal.day_group as requested_day_group,
      coalesce(params.wanted_day_label, cal.day_label) as requested_day_label,
      params.q,
      params.loc,
      params.wanted_shift,
      params.wanted_day_group as param_day_group
    from public.projects p
    join public.companies c on c.project_id = p.id
    join public.bus_routes br on br.company_id = c.id
    join public.bus_stops bs on bs.route_id = br.id
    left join public.knowledge_sources ks on ks.id = br.knowledge_source_id
    cross join params
    left join public.bus_route_service_days cal
      on cal.company_id = c.id
     and cal.route_group_key = br.route_group_key
     and cal.day_group = params.wanted_day_group
     and cal.service_type = case
       when br.direction = 'outbound' and br.shift in ('day', 'admin') then 'outbound_admin_and_day'
       when br.direction = 'outbound' and br.shift = 'night' then 'outbound_night'
       when br.direction = 'return' and br.shift = 'night' then 'return_night'
       when br.direction = 'return' and br.shift = 'admin' then 'return_admin'
       when br.direction = 'return' and br.shift = 'day' then 'return_day'
       else null
     end
    where p.slug = p_project_slug
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and br.direction = params.wanted_direction
      and (
        params.wanted_shift is null
        or br.shift = params.wanted_shift
        or (params.wanted_shift = 'admin' and br.direction = 'outbound' and br.shift = 'day')
      )
      and bs.scheduled_time is not null
  ),
  scored as (
    select
      *,
      exists (
        select 1
        from unnest(coalesce(base.stop_aliases, '{}'::text[])) a
        where base.q like '%' || public.normalize_search_text(a) || '%'
           or (base.loc <> '' and public.normalize_search_text(a) like '%' || base.loc || '%')
      ) as stop_alias_match,
      (
        base.q like '%' || public.normalize_search_text(base.route_name) || '%'
        or base.q like '%' || base.route_group_key || '%'
        or (base.loc <> '' and base.route_group_key like '%' || base.loc || '%')
      ) as route_match,
      greatest(
        similarity(public.normalize_search_text(base.stop_name), base.q),
        similarity(public.normalize_search_text(base.route_name), base.q),
        similarity(base.route_group_key, base.q)
      ) as sim_score
    from base
  ),
  available_scored as (
    select
      *,
      bool_or(stop_alias_match or route_match) over () as has_direct_match
    from scored
    where
      param_day_group is null
      or (
        coalesce(availability_code, 'A') <> 'X'
        and (
          availability_code is null
          or (availability_code = 'M' and coalesce(mode, '') ilike 'merged%')
          or (availability_code = 'A' and coalesce(mode, '') not ilike 'merged%')
        )
      )
  ),
  unavailable_candidates as (
    select
      c.name as company_name,
      rsd.route_group_name as route_name,
      null::text as route_variant,
      case
        when rsd.service_type in ('outbound_night', 'return_night') then 'night'
        when rsd.service_type = 'return_admin' then 'admin'
        else 'day'
      end as shift,
      case
        when rsd.service_type like 'return_%' then 'return'
        else 'outbound'
      end as direction,
      null::integer as stop_order,
      null::text as stop_name,
      null::text as scheduled_time,
      null::text as area,
      null::text as mode,
      ks.source_name,
      null::text as source_page,
      'route unavailable on requested day' as match_reason,
      params.wanted_day_group as requested_day_group,
      params.wanted_day_label as requested_day_label,
      rsd.availability_code
    from params
    join public.projects p on p.slug = p_project_slug
    join public.companies c on c.project_id = p.id
    join public.bus_route_service_days rsd on rsd.company_id = c.id
    left join public.knowledge_sources ks on ks.id = rsd.knowledge_source_id
    where params.wanted_day_group is not null
      and rsd.day_group = params.wanted_day_group
      and rsd.availability_code = 'X'
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and params.q like '%' || public.normalize_search_text(rsd.route_group_name) || '%'
      and (
        params.wanted_shift is null
        or (
          params.wanted_shift = 'night'
          and rsd.service_type in ('outbound_night', 'return_night')
        )
        or (
          params.wanted_shift = 'day'
          and rsd.service_type in ('outbound_admin_and_day', 'return_day')
        )
        or (
          params.wanted_shift = 'admin'
          and rsd.service_type in ('outbound_admin_and_day', 'return_admin')
        )
      )
      and (
        params.wanted_direction = 'outbound'
        and rsd.service_type in ('outbound_admin_and_day', 'outbound_night')
        or params.wanted_direction = 'return'
        and rsd.service_type in ('return_night', 'return_admin', 'return_day')
      )
  ),
  missing_detail_candidates as (
    select
      c.name as company_name,
      rsd.route_group_name as route_name,
      null::text as route_variant,
      case
        when rsd.service_type in ('outbound_night', 'return_night') then 'night'
        when rsd.service_type = 'return_admin' then 'admin'
        else 'day'
      end as shift,
      case
        when rsd.service_type like 'return_%' then 'return'
        else 'outbound'
      end as direction,
      null::integer as stop_order,
      null::text as stop_name,
      null::text as scheduled_time,
      null::text as area,
      null::text as mode,
      ks.source_name,
      null::text as source_page,
      'route has no detailed timing in source' as match_reason,
      params.wanted_day_group as requested_day_group,
      params.wanted_day_label as requested_day_label,
      rsd.availability_code
    from params
    join public.projects p on p.slug = p_project_slug
    join public.companies c on c.project_id = p.id
    join public.bus_route_service_days rsd on rsd.company_id = c.id
    left join public.knowledge_sources ks on ks.id = rsd.knowledge_source_id
    where params.q like '%' || public.normalize_search_text(rsd.route_group_name) || '%'
      and (
        p_company_query is null
        or public.normalize_search_text(c.name) like '%' || public.normalize_search_text(p_company_query) || '%'
        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
      )
      and (
        params.wanted_day_group is null
        or rsd.day_group = params.wanted_day_group
      )
      and rsd.availability_code <> 'X'
      and (
        params.wanted_shift is null
        or (
          params.wanted_shift = 'night'
          and rsd.service_type in ('outbound_night', 'return_night')
        )
        or (
          params.wanted_shift = 'day'
          and rsd.service_type in ('outbound_admin_and_day', 'return_day')
        )
        or (
          params.wanted_shift = 'admin'
          and rsd.service_type in ('outbound_admin_and_day', 'return_admin')
        )
      )
      and (
        params.wanted_direction = 'outbound'
        and rsd.service_type in ('outbound_admin_and_day', 'outbound_night')
        or params.wanted_direction = 'return'
        and rsd.service_type in ('return_night', 'return_admin', 'return_day')
      )
      and not exists (
        select 1
        from public.bus_routes br
        where br.company_id = c.id
          and br.route_group_key = rsd.route_group_key
          and br.direction = params.wanted_direction
          and (
            params.wanted_shift is null
            or br.shift = params.wanted_shift
            or (params.wanted_shift = 'admin' and params.wanted_direction = 'outbound' and br.shift = 'day')
          )
      )
  ),
  filtered as (
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      case
        when stop_alias_match then 'matched stop/location alias'
        when route_match then 'matched route name'
        else 'broad timetable match'
      end as match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      sim_score,
      stop_alias_match,
      route_match
    from available_scored
    where case
      when has_direct_match then stop_alias_match or route_match
      when exists (select 1 from unavailable_candidates) then false
      when exists (select 1 from missing_detail_candidates) then false
      else sim_score > 0.16
    end
  ),
  unavailable as (
    select *
    from unavailable_candidates
    where not exists (select 1 from filtered)
  ),
  missing_detail as (
    select *
    from missing_detail_candidates
    where not exists (select 1 from filtered)
      and not exists (select 1 from unavailable)
  )
  select
    company_name,
    route_name,
    route_variant,
    shift,
    direction,
    stop_order,
    stop_name,
    scheduled_time,
    area,
    mode,
    source_name,
    source_page,
    match_reason,
    requested_day_group,
    requested_day_label,
    availability_code
  from (
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      (case when stop_alias_match then 100 else 0 end
       + case when route_match then 60 else 0 end
       + sim_score * 30) as rank_score
    from filtered
    union all
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      -1::numeric as rank_score
    from unavailable
    union all
    select
      company_name,
      route_name,
      route_variant,
      shift,
      direction,
      stop_order,
      stop_name,
      scheduled_time,
      area,
      mode,
      source_name,
      source_page,
      match_reason,
      requested_day_group,
      requested_day_label,
      availability_code,
      -2::numeric as rank_score
    from missing_detail
  ) ranked
  order by rank_score desc, route_name nulls last, stop_order nulls last
  limit least(greatest(coalesce(p_limit, 20), 1), 50);
$function$;

commit;
