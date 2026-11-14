import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  {
    path: 'model-config',
    loadComponent: () =>
      import('./features/model-config/model-config.component').then((m) => m.ModelConfigComponent),
    title: 'Cấu hình model · Tuyen Pham',
  },
  {
    path: '',
    loadComponent: () =>
      import('./features/catalog/catalog.component').then((m) => m.CatalogComponent),
    title: 'Tuyen Pham - Tư vấn khóa học',
  },
  {
    path: 'courses/:slug',
    loadComponent: () =>
      import('./features/course/course.component').then((m) => m.CourseComponent),
    title: 'Khám phá khóa học · Tuyen Pham',
  },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/auth.component').then((m) => m.AuthComponent),
    title: 'Đăng nhập · Tuyen Pham',
  },
  {
    path: 'register',
    loadComponent: () => import('./features/auth/auth.component').then((m) => m.AuthComponent),
    title: 'Tạo tài khoản · Tuyen Pham',
  },
  {
    path: 'my-learning',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/my-learning/my-learning.component').then((m) => m.MyLearningComponent),
    title: 'Góc học tập · Tuyen Pham',
  },
  {
    path: 'checkout/:slug',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/checkout/checkout.component').then((m) => m.CheckoutComponent),
    title: 'Đăng ký khóa học · Tuyen Pham',
  },
  {
    path: 'learn/:slug',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/learning/learning.component').then((m) => m.LearningComponent),
    title: 'Không gian học tập · Tuyen Pham',
  },
  {
    path: '**',
    loadComponent: () => import('./shared/not-found.component').then((m) => m.NotFoundComponent),
    title: 'Không tìm thấy trang · Tuyen Pham',
  },
];
