class AddCachedLabelsList < ActiveRecord::Migration[7.0]
  def change
    add_column :conversations, :cached_label_list, :string
    Conversation.reset_column_information
    # NOTE: acts-as-taggable-on v12 removed ActsAsTaggableOn::Taggable::Cache; the column is still used by the app.
  end
end
