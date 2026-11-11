import { Routes } from '@angular/router';
import { adminGuard, authGuard, equipeGuard, inicioGuard, visitanteGuard } from './services/auth.guard';
import { ShellComponent } from './pages/shell/shell.component';

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
      // Tela inicial conforme o perfil (o guard sempre redireciona)
      { path: '', pathMatch: 'full', canActivate: [inicioGuard], children: [] },
      {
        path: 'visao-geral',
        canActivate: [equipeGuard],   // só Admin e Colaborador
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
      {
        path: 'clientes',
        canActivate: [equipeGuard],
        loadComponent: () => import('./pages/clientes/clientes.component').then(m => m.ClientesComponent),
        title: 'Clientes · W.L Energy',
      },
      {
        path: 'usuarios',
        canActivate: [adminGuard],   // equipe WL: só Admin
        loadComponent: () => import('./pages/usuarios/usuarios.component').then(m => m.UsuariosComponent),
        title: 'Usuários · W.L Energy',
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
