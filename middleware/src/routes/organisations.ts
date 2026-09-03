import { Router } from 'express';
import { asyncHandler } from '../asyncHandler.js';
import { blesta } from '../blesta/client.js';

// Maps GET/POST /organisations onto Blesta's clients model. Blesta's client
// fields (company, address, status) don't line up 1:1 with synelia-cloud's
// richer Organisation shape (secteur, tenantPlan, consommationVcpu, ...) --
// those extra fields belong in this middleware's own store once it has one,
// keyed by the Blesta client id. This route only proves the Blesta half.
export const organisationsRouter = Router();

function toOrganisation(client: any) {
  return {
    id: String(client.id),
    nom: client.company || `${client.first_name} ${client.last_name}`,
    pays: client.country ?? '',
    statut: client.status === 'active' ? 'active' : client.status === 'inactive' ? 'suspendue' : 'fermee',
    createdAt: client.date_added,
  };
}

organisationsRouter.get(
  '/',
  asyncHandler(async (_req, res) => {
    const clients = await blesta.call<any[]>('clients', 'getList');
    res.json(clients.map(toOrganisation));
  })
);

organisationsRouter.get(
  '/:orgId',
  asyncHandler(async (req, res) => {
    const client = await blesta.call<any>('clients', 'get', { client_id: req.params.orgId });
    if (!client) return res.status(404).json({ error: 'not found' });
    res.json(toOrganisation(client));
  })
);
