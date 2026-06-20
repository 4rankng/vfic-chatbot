-- Seed the first VFIC miniCRM admin after confirming the email address.
--
-- Usage:
--   docker run --rm -e PGPASSWORD="$SUPABASE_PASSWORD" \
--     -v "$PWD/supabase:/supabase:ro" postgres:17-alpine \
--     psql "host=aws-1-ap-northeast-2.pooler.supabase.com port=5432 dbname=postgres user=postgres.vichwmxeptglqmzefsiq sslmode=require" \
--     -v admin_email='admin@example.com' \
--     -v admin_password='replace-with-temporary-password' \
--     -f /supabase/seed_vfic_minicrm_admin.sql

\set ON_ERROR_STOP on

create temp table vfic_seed_params as
select :'admin_email'::text as admin_email,
       :'admin_password'::text as admin_password;

do $$
declare
  v_email text;
  v_password text;
  v_user_id uuid;
begin
  select admin_email, admin_password
    into v_email, v_password
    from vfic_seed_params;

  if v_email is null or btrim(v_email) = '' or v_email = 'admin@example.com' then
    raise exception 'admin_email must be set to the confirmed VFIC admin email';
  end if;

  if v_password is null or length(v_password) < 12 then
    raise exception 'admin_password must be set and at least 12 characters';
  end if;

  select id into v_user_id
  from auth.users
  where lower(email) = lower(v_email)
  limit 1;

  if v_user_id is null then
    v_user_id := gen_random_uuid();

    insert into auth.users (
      instance_id,
      id,
      aud,
      role,
      email,
      encrypted_password,
      email_confirmed_at,
      raw_app_meta_data,
      raw_user_meta_data,
      created_at,
      updated_at,
      is_sso_user,
      is_anonymous
    )
    values (
      '00000000-0000-0000-0000-000000000000',
      v_user_id,
      'authenticated',
      'authenticated',
      v_email,
      crypt(v_password, gen_salt('bf')),
      now(),
      '{"provider":"email","providers":["email"]}'::jsonb,
      '{}'::jsonb,
      now(),
      now(),
      false,
      false
    );

    insert into auth.identities (
      provider_id,
      user_id,
      identity_data,
      provider,
      last_sign_in_at,
      created_at,
      updated_at
    )
    values (
      v_email,
      v_user_id,
      jsonb_build_object('sub', v_user_id::text, 'email', v_email, 'email_verified', true, 'phone_verified', false),
      'email',
      now(),
      now(),
      now()
    );
  end if;

  insert into public.profiles (id, email, full_name, role, created_at, updated_at)
  values (v_user_id, v_email, split_part(v_email, '@', 1), 'admin', now(), now())
  on conflict (id) do update
    set email = excluded.email,
        role = 'admin',
        updated_at = now();
end $$;
