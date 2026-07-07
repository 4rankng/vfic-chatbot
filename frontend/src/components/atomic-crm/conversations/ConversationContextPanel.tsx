import { useMemo } from "react";
import type { Lead } from "../types";
import {
  BusFront,
  CalendarDays,
  Check,
  CircleDollarSign,
  FileBadge,
  Handshake,
  Home,
  MapPin,
  NotepadText,
  Phone,
  UserRound,
  type LucideIcon,
} from "lucide-react";

const display = (value: unknown, fallback = "Chưa có dữ liệu") => {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
};

type CandidateInfoItem = {
  key: string;
  label: string;
  value: string;
  complete: boolean;
  Icon: LucideIcon;
};

const hasMeaningfulValue = (value: unknown) =>
  display(value) !== "Chưa có dữ liệu";

const notesInclude = (notes: string | null | undefined, terms: string[]) => {
  const normalized = notes?.toLocaleLowerCase("vi-VN") ?? "";
  return terms.some((term) => normalized.includes(term));
};

export const ConversationContextPanel = ({
  lead,
  open,
  onClose,
  onOpenProfile,
}: {
  lead?: Lead;
  open: boolean;
  onClose: () => void;
  onOpenProfile: () => void;
}) => {
  const candidateInfoItems = useMemo<CandidateInfoItem[]>(() => {
    const notes = lead?.notes;
    const dateOfBirth = lead?.birth_year
      ? String(lead.birth_year)
      : lead?.age
        ? `${lead.age} tuổi`
        : "";
    const area = [lead?.region, lead?.living_area].filter(Boolean).join(" · ");
    const hasCitizenId = notesInclude(notes, ["cccd", "cmnd", "căn cước"]);
    const hasHousing = notesInclude(notes, [
      "chỗ ở",
      "cho o",
      "nhà trọ",
      "nha tro",
      "ký túc",
      "ky tuc",
      "ktx",
    ]);
    const hasPickup = notesInclude(notes, [
      "đưa đón",
      "dua don",
      "xe đưa",
      "xe dua",
      "xe đón",
      "xe don",
      "bus",
      "tuyến xe",
      "tuyen xe",
    ]);

    return [
      {
        key: "name",
        label: "Họ tên",
        value: display(lead?.name),
        complete: hasMeaningfulValue(lead?.name),
        Icon: UserRound,
      },
      {
        key: "phone",
        label: "Số điện thoại",
        value: display(lead?.phone),
        complete: hasMeaningfulValue(lead?.phone),
        Icon: Phone,
      },
      {
        key: "birth",
        label: "Ngày sinh / tuổi",
        value: display(dateOfBirth),
        complete: Boolean(dateOfBirth),
        Icon: CalendarDays,
      },
      {
        key: "citizen-id",
        label: "CCCD",
        value: hasCitizenId ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasCitizenId,
        Icon: FileBadge,
      },
      {
        key: "experience",
        label: "Kinh nghiệm",
        value: display(lead?.years_experience),
        complete: hasMeaningfulValue(lead?.years_experience),
        Icon: FileBadge,
      },
      {
        key: "expectation",
        label: "Mong muốn",
        value: display(lead?.desired_job),
        complete: hasMeaningfulValue(lead?.desired_job),
        Icon: Handshake,
      },
      {
        key: "salary",
        label: "Mức lương",
        value: display(lead?.expected_salary),
        complete: hasMeaningfulValue(lead?.expected_salary),
        Icon: CircleDollarSign,
      },
      {
        key: "housing",
        label: "Chỗ ở",
        value: hasHousing ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasHousing,
        Icon: Home,
      },
      {
        key: "pickup",
        label: "Xe đưa đón",
        value: hasPickup ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasPickup,
        Icon: BusFront,
      },
      {
        key: "area",
        label: "Khu vực",
        value: display(area),
        complete: Boolean(area),
        Icon: MapPin,
      },
      {
        key: "address",
        label: "Địa chỉ hiện tại",
        value: display(lead?.address),
        complete: hasMeaningfulValue(lead?.address),
        Icon: Home,
      },
      {
        key: "notes",
        label: "Ghi chú",
        value: display(lead?.notes),
        complete: hasMeaningfulValue(lead?.notes),
        Icon: NotepadText,
      },
    ];
  }, [lead]);

  return (
    <aside
      className={`panel right-panel ${open ? "context-open" : ""}`}
      aria-label="Thông tin ứng viên"
      aria-hidden={!open}
    >
      <header className="profile-header">
        <div className="profile-title">
          <UserRound className="icon" aria-hidden="true" />
          <span className="profile-title-copy">
            <span>{display(lead?.name, "Ứng viên")}</span>
            <small>{display(lead?.phone, "Chưa có số điện thoại")}</small>
          </span>
        </div>
        <div className="context-header-actions">
          <button
            type="button"
            className="context-open-profile"
            onClick={onOpenProfile}
          >
            Mở hồ sơ
          </button>
          <button
            type="button"
            className="context-close"
            onClick={onClose}
            aria-label="Đóng thông tin ứng viên"
          >
            ×
          </button>
        </div>
      </header>

      <div className="profile-scroll">
        <section className="context-card">
          <div className="section-head">
            <h3>Thông tin ứng viên</h3>
          </div>
          <div className="candidate-info-grid">
            {candidateInfoItems.map((item) => (
              <CandidateInfoRow key={item.key} item={item} />
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
};

const CandidateInfoRow = ({ item }: { item: CandidateInfoItem }) => {
  const Icon = item.Icon;
  return (
    <div className={`candidate-info-row ${item.complete ? "filled" : ""}`}>
      <span className="candidate-info-icon">
        <Icon className="icon" aria-hidden="true" />
      </span>
      <span className="candidate-info-copy">
        <span className="candidate-info-label">{item.label}</span>
        <span className="candidate-info-value">{item.value}</span>
      </span>
      <span className="candidate-info-state" aria-hidden="true">
        {item.complete ? <Check className="icon" /> : null}
      </span>
    </div>
  );
};
