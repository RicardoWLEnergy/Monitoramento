import { Routes } from '@angular/router';
import { authGuard, visitanteGuard } from './core/auth.guard';
import { ShellComponent } from './layout/shell.component';

const emConstrucao = (titulo: string) => ({
  loadComponent: () => import('./pages/em-construcao/em-construcao.component').then(m => m.EmConstrucaoComponent),
  data: { titulo },
});

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [visitanteGuard],
    loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent),
    title: 'Entrar · W.L Energy',
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'visao-geral' },
      {
        path: 'visao-geral',
        loadComponent: () => import('./pages/visao-geral/visao-geral.component').then(m => m.VisaoGeralComponent),
        title: 'Visão geral · W.L Energy',
      },
      {
        path: 'usinas',
        loadComponent: () => import('./pages/usinas/usinas.component').then(m => m.UsinasComponent),
        title: 'Usinas · W.L Energy',
      },
      {
        path: 'usinas/:id',
        loadComponent: () => import('./pages/usina-detalhe/usina-detalhe.component').then(m => m.UsinaDetalheComponent),
        title: 'Usina · W.L Energy',
      },
      { path: 'alertas',    ...emConstrucao('Alertas'),    title: 'Alertas · W.L Energy' },
      { path: 'relatorios', ...emConstrucao('Relatórios'), title: 'Relatórios · W.L Energy' },
      { path: 'clientes',   ...emConstrucao('Clientes'),   title: 'Clientes · W.L Energy' },
      { path: 'usuarios',   ...emConstrucao('Usuários'),   title: 'Usuários · W.L Energy' },
    ],
  },
  { path: '**', redirectTo: '' },
];
