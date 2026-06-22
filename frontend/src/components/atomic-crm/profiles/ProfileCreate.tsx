import { CreateBase, useNotify, useRedirect, Form } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { TopToolbar } from "../layout/TopToolbar";
import { Button } from "@/components/ui/button";
import { useDataProvider } from "ra-core";
import { useState } from "react";
import type { CrmDataProvider } from "../providers/supabase/dataProvider";

export const ProfileCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (data: any) => {
    setIsSubmitting(true);
    try {
      await dataProvider.createProfile(data);
      notify("User created successfully", { type: "success" });
      redirect("/users");
    } catch (e: any) {
      notify(e.message, { type: "error" });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <CreateBase>
      <TopToolbar>
        <h2 className="text-xl font-semibold mr-auto">Create User</h2>
      </TopToolbar>
      <Card className="mt-4 max-w-2xl">
        <CardContent className="pt-6">
          <Form onSubmit={onSubmit}>
            <div className="flex flex-col gap-4">
              <TextInput source="email" label="Email" type="email" isRequired />
              <TextInput
                source="password"
                label="Password"
                type="password"
                isRequired
              />
              <TextInput source="full_name" label="Full Name" isRequired />
              <SelectInput
                source="role"
                label="Role"
                choices={[
                  { id: "admin", name: "Admin" },
                  { id: "recruiter", name: "Recruiter" },
                ]}
                isRequired
              />
              <Button type="submit" disabled={isSubmitting}>
                Create User
              </Button>
            </div>
          </Form>
        </CardContent>
      </Card>
    </CreateBase>
  );
};
