create table if not exists public.web_profiles (
    auth_user_id uuid primary key references auth.users (id) on delete cascade,
    source_user_id bigint unique not null,
    username text unique not null,
    display_name text not null,
    role text not null,
    enabled boolean not null default true
);

create table if not exists public.clusteres (
    id bigint primary key,
    nombre_cluster text unique not null
);

create table if not exists public.proyectos (
    id bigint primary key,
    cluster text,
    nombre text not null,
    municipio text,
    departamento text,
    direccion text,
    latitud text,
    longitud text,
    area double precision,
    radicado text,
    cod_validacion text,
    circuito text,
    coord_conexion text,
    fecha_creacion text,
    estado_general text,
    capacidad_kw double precision,
    req_servidumbre integer,
    req_contrato integer,
    num_paneles integer,
    pot_panel double precision,
    num_inversores integer,
    modelos_inversores text,
    en_operacion integer not null default 0
);

alter table public.proyectos
    add column if not exists en_operacion integer not null default 0;

create table if not exists public.requisitos (
    id bigint primary key,
    proyecto_id bigint not null references public.proyectos (id) on delete cascade,
    categoria text,
    descripcion text,
    entidad text,
    estado text,
    fecha_radicacion text,
    fecha_limite text,
    fecha_final text,
    observaciones text
);

alter table public.web_profiles enable row level security;
alter table public.clusteres enable row level security;
alter table public.proyectos enable row level security;
alter table public.requisitos enable row level security;

grant select on public.web_profiles, public.clusteres, public.proyectos, public.requisitos to authenticated;
revoke all on public.web_profiles, public.clusteres, public.proyectos, public.requisitos from anon;
revoke insert, update, delete on public.web_profiles, public.clusteres, public.proyectos, public.requisitos from authenticated;

drop policy if exists "users read own web profile" on public.web_profiles;
create policy "users read own web profile"
    on public.web_profiles for select to authenticated
    using (auth_user_id = auth.uid());

drop policy if exists "enabled users read clusters" on public.clusteres;
create policy "enabled users read clusters"
    on public.clusteres for select to authenticated
    using (
        exists (
            select 1 from public.web_profiles
            where auth_user_id = auth.uid() and enabled
        )
    );

drop policy if exists "enabled users read projects" on public.proyectos;
create policy "enabled users read projects"
    on public.proyectos for select to authenticated
    using (
        exists (
            select 1 from public.web_profiles
            where auth_user_id = auth.uid() and enabled
        )
    );

drop policy if exists "enabled users read requirements" on public.requisitos;
create policy "enabled users read requirements"
    on public.requisitos for select to authenticated
    using (
        exists (
            select 1 from public.web_profiles
            where auth_user_id = auth.uid() and enabled
        )
    );