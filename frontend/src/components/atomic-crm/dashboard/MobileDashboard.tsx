import { useGetList } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, MessageCircle } from "lucide-react";
import MobileHeader from "../layout/MobileHeader";
import { MobileContent } from "../layout/MobileContent";

const Wrapper = ({ children }: { children: React.ReactNode }) => {
  return (
    <>
      <MobileHeader>
        <div className="flex items-center gap-2 text-secondary-foreground no-underline py-3">
          <h1 className="text-xl font-semibold">VFIC CRM</h1>
        </div>
      </MobileHeader>
      <MobileContent>{children}</MobileContent>
    </>
  );
};

export const MobileDashboard = () => {
  const { total: totalLeads } = useGetList("leads", {
    pagination: { page: 1, perPage: 1 },
  });

  const { total: totalConversations } = useGetList("conversations", {
    pagination: { page: 1, perPage: 1 },
  });

  return (
    <Wrapper>
      <div className="grid grid-cols-1 gap-4 mt-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Total Leads</CardTitle>
            <Users className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalLeads ?? "-"}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Conversations</CardTitle>
            <MessageCircle className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalConversations ?? "-"}</div>
          </CardContent>
        </Card>
      </div>
    </Wrapper>
  );
};
