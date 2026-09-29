import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useHotkeys } from "react-hotkeys-hook";
import type { FC } from "react";
import { FolderPlus, Library, UserPlus, UserRound } from "lucide-react";

import { CommandMenu } from "@/components/application/command-menus/command-menu";
import type { CommandMenuGroupType } from "@/components/application/command-menus/command-menu";

import { useCompiledRuntime } from "../../capabilities/runtime-context";
import { useRoleActions } from "../../hooks/useRoleActions";
import {
  getWorkspaceDestinations,
  type WorkspaceRole,
} from "../workspace-nav-model";

type PaletteEntry = {
  id: string;
  label: string;
  to: string;
  icon: FC<{ className?: string }>;
};

type PaletteGroup = {
  id: string;
  title: string;
  entries: readonly PaletteEntry[];
};

type PaletteAction = PaletteEntry & { adminsOnly?: boolean };

const ACTIONS: readonly PaletteAction[] = [
  {
    id: "action.create-project",
    label: "Tạo dự án",
    to: "/projects/create",
    icon: FolderPlus,
  },
  {
    id: "action.create-knowledge-base",
    label: "Tạo cơ sở kiến thức",
    to: "/knowledge_bases/create",
    icon: Library,
    adminsOnly: true,
  },
  {
    id: "action.create-persona",
    label: "Tạo Agent",
    to: "/personas/create",
    icon: UserPlus,
    adminsOnly: true,
  },
  {
    id: "action.create-user",
    label: "Tạo tài khoản",
    to: "/users/create",
    icon: UserPlus,
    adminsOnly: true,
  },
  {
    id: "action.profile",
    label: "Hồ sơ cá nhân",
    to: "/profile",
    icon: UserRound,
  },
];

/**
 * ⌘K palette: every destination the signed-in role may reach plus the create
 * actions, searched from one input. Untitled UI's command menu owns the dialog,
 * the filtering and the keyboard handling; this module supplies the groups, the
 * role filter and the navigation.
 */
export const CommandPalette = () => {
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();
  const { isAdmin } = useRoleActions();
  const { navigation } = useCompiledRuntime();

  const role: WorkspaceRole = isAdmin ? "admin" : "recruiter";

  // The library registers ⌘K to focus its input; the palette must also open, or
  // the shortcut does nothing while the dialog is closed.
  useHotkeys("meta+k,ctrl+k", () => setIsOpen(true), {
    enableOnFormTags: true,
  });

  const groups = useMemo<readonly PaletteGroup[]>(() => {
    const destinations = getWorkspaceDestinations(role, navigation);

    return [
      {
        id: "navigation",
        title: "Điều hướng",
        entries: destinations.map((destination) => ({
          id: `nav.${destination.id}`,
          label: destination.label,
          to: destination.to,
          icon: destination.Icon,
        })),
      },
      {
        id: "actions",
        title: "Hành động",
        entries: ACTIONS.filter((action) => !action.adminsOnly || isAdmin),
      },
    ];
  }, [isAdmin, navigation, role]);

  // The library reads a flat item list for filtering and hotkeys; the rendering
  // below uses the typed groups so no item shape has to be re-narrowed.
  const items = useMemo<CommandMenuGroupType[]>(
    () =>
      groups.map((group) => ({
        id: group.id,
        title: group.title,
        items: group.entries.map((entry) => ({
          id: entry.id,
          label: entry.label,
          type: "icon" as const,
          icon: entry.icon,
          href: entry.to,
        })),
      })),
    [groups],
  );

  const handleSelect = (keys: Iterable<unknown>) => {
    const [selected] = Array.from(keys);
    const target = groups
      .flatMap((group) => group.entries)
      .find((entry) => entry.id === selected)?.to;
    setIsOpen(false);
    if (target) void navigate(target);
  };

  return (
    <CommandMenu
      items={items}
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      onSelectionChange={handleSelect}
      shortcut="⌘k"
      placeholder="Tìm kiếm hoặc chuyển nhanh"
      dialogClassName="uu-scope"
      overlayClassName="uu-scope"
    >
      <CommandMenu.List>
        {groups.map((group) => (
          <CommandMenu.Section key={group.id} id={group.id} title={group.title}>
            {group.entries.map((entry) => (
              <CommandMenu.Item
                key={entry.id}
                id={entry.id}
                label={entry.label}
                type="icon"
                icon={entry.icon}
                href={entry.to}
              />
            ))}
          </CommandMenu.Section>
        ))}
      </CommandMenu.List>
    </CommandMenu>
  );
};
