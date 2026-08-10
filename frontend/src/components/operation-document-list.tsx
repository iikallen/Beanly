import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { formatInventoryDate } from "@/lib/inventory";

export type OperationDocumentRow = {
  id: string;
  number: string;
  description: string;
  status: string;
  date: string;
};

export function OperationDocumentList({
  rows,
  basePath,
  loading,
  error,
  emptyTitle,
  emptyMessage,
}: {
  rows: OperationDocumentRow[];
  basePath: string;
  loading: boolean;
  error: string;
  emptyTitle: string;
  emptyMessage: string;
}) {
  if (error) return <div className="inventory-state is-error" role="alert"><strong>Documents could not be loaded.</strong><span>{error}</span></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Loading documents…</div>;
  if (rows.length === 0) return <div className="inventory-state"><strong>{emptyTitle}</strong><span>{emptyMessage}</span></div>;
  return (
    <div className="inventory-table-wrap" tabIndex={0} aria-label="Documents table">
      <table className="inventory-table operation-documents-table">
        <thead><tr><th>Number</th><th>Details</th><th>Status</th><th>Date</th><th><span className="sr-only">Open</span></th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.id}>
          <td><Link className="inventory-item-link" href={`${basePath}/${row.id}`}>{row.number}</Link></td>
          <td>{row.description}</td>
          <td><span className={`purchasing-status status-${row.status.toLowerCase()}`}>{row.status.toLowerCase().replaceAll("_", " ")}</span></td>
          <td>{formatInventoryDate(row.date)}</td>
          <td><Link className="purchasing-row-link" href={`${basePath}/${row.id}`} aria-label={`Open ${row.number}`}><ChevronRight aria-hidden="true" /></Link></td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}
