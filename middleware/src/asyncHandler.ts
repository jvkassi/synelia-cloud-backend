import type { NextFunction, Request, RequestHandler, Response } from 'express';

// Express 4 doesn't forward rejected promises from async handlers to the
// error middleware on its own -- wrap every handler with this so a thrown
// OpenStack/Blesta error becomes a 500 instead of an unhandled rejection.
export function asyncHandler(fn: (req: Request, res: Response, next: NextFunction) => Promise<unknown>): RequestHandler {
  return (req, res, next) => {
    fn(req, res, next).catch(next);
  };
}
