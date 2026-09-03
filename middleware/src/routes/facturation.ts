import { Router } from 'express';
import { asyncHandler } from '../asyncHandler.js';
import { blesta } from '../blesta/client.js';

// Maps GET /facturation/factures onto Blesta's invoices model.
export const facturationRouter = Router();

function toInvoice(invoice: any) {
  return {
    id: String(invoice.id),
    orgId: String(invoice.client_id),
    numero: invoice.id_code,
    periode: `${invoice.date_billed} - ${invoice.date_due}`,
    lignes: (invoice.line_items ?? []).map((line: any) => ({
      libelle: line.description,
      ref: String(line.id),
      quantite: Number(line.qty),
      pu: Number(line.unit_cost),
      total: Number(line.qty) * Number(line.unit_cost),
    })),
    sousTotal: Number(invoice.subtotal),
    tvaPct: 0, // Blesta reports absolute tax amounts, not a rate -- see invoice.tax
    total: Number(invoice.total),
    devise: invoice.currency,
    statut:
      invoice.status === 'active'
        ? 'emise'
        : invoice.status === 'paid'
          ? 'payee'
          : invoice.status === 'void'
            ? 'annulee'
            : 'brouillon',
    pdfUrl: `/facturation/factures/${invoice.id}/pdf`,
    echeance: invoice.date_due,
  };
}

facturationRouter.get(
  '/factures',
  asyncHandler(async (_req, res) => {
    const invoices = await blesta.call<any[]>('invoices', 'getAll');
    res.json(invoices.map(toInvoice));
  })
);

facturationRouter.get(
  '/factures/:factureId',
  asyncHandler(async (req, res) => {
    const invoice = await blesta.call<any>('invoices', 'get', { invoice_id: req.params.factureId });
    if (!invoice) return res.status(404).json({ error: 'not found' });
    res.json(toInvoice(invoice));
  })
);
