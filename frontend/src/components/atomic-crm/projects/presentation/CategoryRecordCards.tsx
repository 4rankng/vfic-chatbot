import {
  fieldLabel,
  type CategoryDocumentView,
  type CategoryRecordFieldView,
} from "../domain/category-markdown-reader";

/** Read view of one category's markdown: one card per record, fields in
 *  schema order, lists as chips, tables as compact tables. Null/empty fields
 *  are dropped by the reader; labels are display-only Vietnamese. */
export const CategoryRecordCards = ({
  view,
}: {
  view: CategoryDocumentView;
}) => (
  <div className="project-category-record-cards">
    {view.records.map((record) => (
      <article
        key={record.id}
        className="project-category-record-card"
        aria-label={record.title}
      >
        <h4 className="project-category-record-title">{record.title}</h4>
        {record.malformed.length > 0 ? (
          <p className="project-category-record-malformed">
            {record.malformed.length} dòng không đọc được — chọn «Xem markdown»
            để kiểm tra.
          </p>
        ) : null}
        <dl className="project-category-record-fields">
          {record.fields.map((field) => (
            <RecordField key={field.name} field={field} />
          ))}
        </dl>
      </article>
    ))}
  </div>
);

const RecordField = ({ field }: { field: CategoryRecordFieldView }) => {
  if (field.kind === "list") {
    return (
      <div className="project-category-record-field">
        <dt>{fieldLabel(field.name)}</dt>
        <dd>
          <ul className="project-category-record-chips">
            {field.items.map((item, index) => (
              <li key={`${item}-${index}`}>{item}</li>
            ))}
          </ul>
        </dd>
      </div>
    );
  }
  if (field.kind === "table") {
    return (
      <div className="project-category-record-field">
        <dt>{fieldLabel(field.name)}</dt>
        <dd>
          <table className="project-category-record-table">
            <thead>
              <tr>
                {field.columns.map((column) => (
                  <th key={column}>{fieldLabel(column)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {field.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </dd>
      </div>
    );
  }
  return (
    <div className="project-category-record-field">
      <dt>{fieldLabel(field.name)}</dt>
      <dd>{field.display}</dd>
    </div>
  );
};
