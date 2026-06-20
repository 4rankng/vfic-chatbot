alter table public.conversations
  add column if not exists assigned_recruiter_id uuid references public.profiles(id);

create index if not exists conversations_assigned_recruiter_id_idx
  on public.conversations (assigned_recruiter_id);

create or replace function public.vfic_take_over(p_zalo_chat_id text, p_recruiter uuid)
returns public.conversations
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.conversations;
begin
  if auth.uid() is distinct from p_recruiter then
    raise exception 'takeover forbidden: recruiter must match auth user' using errcode = '42501';
  end if;

  if not exists (
    select 1
    from public.profiles
    where id = p_recruiter
      and role in ('admin', 'recruiter')
  ) then
    raise exception 'takeover forbidden: recruiter profile not allowed' using errcode = '42501';
  end if;

  insert into public.conversations (zalo_chat_id, mode, assigned_recruiter_id, taken_over_at, version)
  values (p_zalo_chat_id, 'human', p_recruiter, now(), 2)
  on conflict (zalo_chat_id) do update
    set mode = 'human',
        assigned_recruiter_id = p_recruiter,
        taken_over_at = now(),
        version = public.conversations.version + 1,
        updated_at = now()
    where public.conversations.assigned_recruiter_id is null
       or public.conversations.assigned_recruiter_id = p_recruiter
  returning * into v_row;

  if v_row.id is null then
    raise exception 'conversation already owned by another recruiter' using errcode = '55006';
  end if;

  return v_row;
end;
$$;

create or replace function public.vfic_release(p_zalo_chat_id text, p_recruiter uuid)
returns public.conversations
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.conversations;
begin
  if auth.uid() is distinct from p_recruiter then
    raise exception 'release forbidden: recruiter must match auth user' using errcode = '42501';
  end if;

  update public.conversations
     set mode = 'bot',
         assigned_recruiter_id = null,
         taken_over_at = null,
         version = public.conversations.version + 1,
         updated_at = now()
   where zalo_chat_id = p_zalo_chat_id
     and assigned_recruiter_id = p_recruiter
  returning * into v_row;

  if v_row.id is null then
    raise exception 'release forbidden: not the assigned recruiter' using errcode = '42501';
  end if;

  return v_row;
end;
$$;
