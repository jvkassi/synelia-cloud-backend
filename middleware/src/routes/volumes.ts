import { Router } from 'express';
import { asyncHandler } from '../asyncHandler.js';
import { provisioner } from '../provisioner/index.js';

export const volumesRouter = Router();

volumesRouter.get(
  '/',
  asyncHandler(async (_req, res) => {
    res.json(await provisioner.listVolumes());
  })
);

volumesRouter.post(
  '/',
  asyncHandler(async (req, res) => {
    const { nom, tailleGo } = req.body ?? {};
    if (!nom || !tailleGo) {
      return res.status(400).json({ error: 'nom and tailleGo are required' });
    }
    res.status(201).json(await provisioner.createVolume({ nom, tailleGo }));
  })
);

volumesRouter.delete(
  '/:volumeId',
  asyncHandler(async (req, res) => {
    await provisioner.deleteVolume(req.params.volumeId);
    res.status(204).end();
  })
);
