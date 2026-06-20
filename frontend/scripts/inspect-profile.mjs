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

  console.log("Logged in. User ID:", authData.user.id);

  const { data, error } = await supabase
    .from("profiles")
    .select("*")
    .eq("id", authData.user.id)
    .single();

  if (error) {
    console.error("Error fetching profile:", error);
  } else {
    console.log("Profile details:", JSON.stringify(data, null, 2));
  }
}

inspect();
