import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/** Bloqueia rotas internas para quem não está logado. */
export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.logado() ? true : inject(Router).createUrlTree(['/login']);
};

/** Impede voltar ao login quem já está logado. */
export const visitanteGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.logado() ? inject(Router).createUrlTree(['/']) : true;
};

/** Só Admin e Colaborador (ex.: cadastro de clientes). */
export const equipeGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.eEquipe() ? true : inject(Router).createUrlTree(['/']);
};

/** Só Admin. */
export const adminGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.eAdmin() ? true : inject(Router).createUrlTree(['/']);
};
