import { Router } from 'express';
import { asyncHandler } from '../asyncHandler.js';
import { provisioner } from '../provisioner/index.js';

// Maps GET/POST /vms, GET/PATCH/DELETE /vms/:id and the start/stop/restart
// actions from synelia-cloud's openapi.json onto the Provisioner interface
// (OpenStack Nova underneath, today). PATCH (materiel/redimensionnement)
// and snapshots aren't wired up yet -- same pattern, next slice.
export const vmsRouter = Router();

vmsRouter.get(
  '/',
  asyncHandler(async (_req, res) => {
    res.json(await provisioner.listVMs());
  })
);

vmsRouter.post(
  '/',
  asyncHandler(async (req, res) => {
    const { nom, flavorId, imageId, networkId } = req.body ?? {};
    if (!nom || !flavorId || !imageId || !networkId) {
      return res.status(400).json({ error: 'nom, flavorId, imageId and networkId are required' });
    }
    res.status(201).json(await provisioner.createVM({ nom, flavorId, imageId, networkId }));
  })
);

vmsRouter.get(
  '/:vmId',
  asyncHandler(async (req, res) => {
    const vm = await provisioner.getVM(req.params.vmId);
    if (!vm) return res.status(404).json({ error: 'not found' });
    res.json(vm);
  })
);

vmsRouter.delete(
  '/:vmId',
  asyncHandler(async (req, res) => {
    await provisioner.deleteVM(req.params.vmId);
    res.status(204).end();
  })
);

vmsRouter.post(
  '/:vmId/demarrage',
  asyncHandler(async (req, res) => {
    await provisioner.startVM(req.params.vmId);
    res.status(202).end();
  })
);

vmsRouter.post(
  '/:vmId/arret',
  asyncHandler(async (req, res) => {
    await provisioner.stopVM(req.params.vmId);
    res.status(202).end();
  })
);

vmsRouter.post(
  '/:vmId/redemarrage',
  asyncHandler(async (req, res) => {
    await provisioner.rebootVM(req.params.vmId);
    res.status(202).end();
  })
);
