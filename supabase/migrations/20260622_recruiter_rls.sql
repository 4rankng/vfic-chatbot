-- RLS updates for VFIC CRM to allow recruiters access

-- Leads
CREATE POLICY "Recruiters can access leads" 
ON public.leads
FOR ALL 
TO authenticated 
USING (
  EXISTS (SELECT 1 FROM profiles WHERE profiles.id = auth.uid() AND (role = 'admin' OR role = 'recruiter'))
);

-- Conversations
CREATE POLICY "Recruiters can access conversations" 
ON public.conversations
FOR ALL 
TO authenticated 
USING (
  EXISTS (SELECT 1 FROM profiles WHERE profiles.id = auth.uid() AND (role = 'admin' OR role = 'recruiter'))
);

-- Chat Histories
CREATE POLICY "Recruiters can view chat histories" 
ON public.vfic_chat_histories
FOR SELECT 
TO authenticated 
USING (
  EXISTS (SELECT 1 FROM profiles WHERE profiles.id = auth.uid() AND (role = 'admin' OR role = 'recruiter'))
);

-- Wait, bots use service_role to bypass RLS, so this only applies to frontend users (authenticated).
-- We can also grant update to chat histories if needed, though they shouldn't edit messages.

-- Ensure Profiles are viewable by self
CREATE POLICY "Users can view their own profile" 
ON public.profiles
FOR SELECT 
TO authenticated 
USING (
  id = auth.uid()
);

-- And Admins can manage all profiles
CREATE POLICY "Admins can manage all profiles" 
ON public.profiles
FOR ALL 
TO authenticated 
USING (
  EXISTS (SELECT 1 FROM profiles WHERE profiles.id = auth.uid() AND role = 'admin')
);
