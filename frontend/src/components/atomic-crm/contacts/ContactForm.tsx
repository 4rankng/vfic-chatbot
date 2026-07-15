import { Create } from "@/components/admin/create";
import { Edit } from "@/components/admin/edit";
import { SimpleForm } from "@/components/admin/simple-form";
import { TextInput } from "@/components/admin/text-input";
import { useInput } from "ra-core";

const HiddenVersionInput = () => {
  const { field } = useInput({ source: "version" });
  return <input type="hidden" {...field} value={field.value ?? ""} />;
};

const Fields = ({ editing = false }: { editing?: boolean }) => (
  <>
    {editing ? <HiddenVersionInput /> : null}
    <TextInput source="display_name" label="Tên hiển thị" />
    <TextInput source="primary_phone" label="Điện thoại" />
    <TextInput source="primary_email" label="Email" type="email" />
    <TextInput source="avatar_url" label="Ảnh đại diện" type="url" />
    <TextInput source="locale" label="Ngôn ngữ" />
  </>
);

export const ContactCreate = () => (
  <Create title="Tạo liên hệ">
    <SimpleForm>
      <Fields />
    </SimpleForm>
  </Create>
);

export const ContactEdit = () => (
  <Edit title="Cập nhật liên hệ" actions={false}>
    <SimpleForm>
      <Fields editing />
    </SimpleForm>
  </Edit>
);
