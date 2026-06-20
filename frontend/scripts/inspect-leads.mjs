import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  "https://vichwmxeptglqmzefsiq.supabase.co",
  "sb_publishable_OzZE-GkhYNIZ1rUOAsn4eQ_ojPeuDDK"
);

async function inspect() {
  const { data: authData, error: authError } = await supabase.auth.signInWithPassword({
    email: "admin@tingting.vip",
    password: "t8fXyXcJzsMLaApT0Bk1YfyzAa1!"
  });

  if (authError) {
    console.error("Auth error:", authError);
    return;
  }

  console.log("Fetching lead records from database...");
  const { data, error } = await supabase
    .from("leads")
    .select("id, name, zalo_id, lead_stage")
    .limit(10);

  if (error) {
    console.error("Error fetching leads:", error);
  } else {
    console.log("Leads found (first 10):", JSON.stringify(data, null, 2));
  }
}

inspect();
