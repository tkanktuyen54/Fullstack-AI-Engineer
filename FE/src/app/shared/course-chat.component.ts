import {
  Component,
  ElementRef,
  OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { CurrencyPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ChatCourse, ChatService, ChatSource, ChatTopic } from '../core/chat.service';
import { AuthService } from '../core/auth.service';
import { applyAnswerEvent } from '../core/chat-stream';
import { errorMessage } from '../core/api.service';
import { ModelConfigService, ModelProvider } from '../core/model-config.service';
import { answerModelLabel, modelFailureMessage } from '../core/chat-model-status';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  courses: ChatCourse[];
  sources: ChatSource[];
  topic: ChatTopic;
  answerMode?: 'course' | 'generated' | 'extractive' | 'not_found' | 'blocked' | 'tool';
  streaming?: boolean;
  modelLabel?: string;
  fallbackReason?: string;
  engine?: string;
}

@Component({
  selector: 'app-course-chat',
  imports: [FormsModule, RouterLink, CurrencyPipe],
  templateUrl: './course-chat.component.html',
  styleUrl: './course-chat.component.css',
})
export class CourseChatComponent implements OnDestroy {
  readonly auth = inject(AuthService);
  readonly models = inject(ModelConfigService);
  readonly answerModelLabel = answerModelLabel;
  readonly modelFailureMessage = modelFailureMessage;
  private readonly chat = inject(ChatService);
  private readonly router = inject(Router);
  private readonly input = viewChild<ElementRef<HTMLTextAreaElement>>('questionInput');
  private readonly log = viewChild<ElementRef<HTMLDivElement>>('messageLog');
  private readonly launcher = viewChild<ElementRef<HTMLButtonElement>>('launcher');
  private controller?: AbortController;
  private nextId = 1;
  readonly open = signal(false);
  readonly pending = signal(false);
  readonly status = signal('');
  readonly error = signal('');
  readonly modelsLoading = signal(false);
  readonly topic = signal<ChatTopic>('courses');
  readonly employeeAccess = computed(
    () =>
      this.auth.user()?.roles?.some((role) => ['HR', 'HR_APPROVER', 'ADMIN'].includes(role)) ??
      false,
  );
  private readonly conversations = signal<Message[]>([]);
  readonly messages = computed(() =>
    this.conversations().filter((item) => item.topic === this.topic()),
  );
  readonly prompts = computed(() =>
    this.topic() === 'employees'
      ? [
          'Có bao nhiêu nhân viên?',
          'Có bao nhiêu nhân viên đang làm việc?',
          'Tìm nhân viên tên Nguyễn Văn An',
        ]
      : this.topic() === 'secops'
        ? [
            'Threat Hunting là gì?',
            'Các bảng dữ liệu của Threat Hunting gồm những gì?',
            'SIEM hoạt động như thế nào?',
          ]
        : [
            'Liệt kê các danh mục khóa học trên Khoa',
            'Mình mới bắt đầu học lập trình',
            'Tìm khóa học dưới 500 nghìn',
          ],
  );
  question = '';

  constructor() {
    let previousUserId: number | undefined;
    effect(() => {
      const userId = this.auth.user()?.id;
      if (userId !== previousUserId || !this.employeeAccess()) {
        this.conversations.update((items) => items.filter((item) => item.topic !== 'employees'));
        if (this.topic() === 'employees') {
          this.controller?.abort();
          this.topic.set('courses');
          this.question = '';
        }
      }
      previousUserId = userId;
    });
  }

  selectProvider(provider: ModelProvider): void {
    if (this.pending() || (provider === 'groq' && !this.models.config()?.groqConfigured)) return;
    this.models.provider.set(provider);
    this.error.set('');
  }

  async loadModels(): Promise<void> {
    this.modelsLoading.set(true);
    try {
      await this.models.load();
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.modelsLoading.set(false);
    }
  }

  selectTopic(topic: ChatTopic): void {
    if (this.pending() || (topic === 'employees' && !this.employeeAccess())) return;
    this.topic.set(topic);
    this.error.set('');
    this.question = '';
    setTimeout(() => this.input()?.nativeElement.focus());
    this.scroll();
  }

  onEnter(event: Event): void {
    const key = event as KeyboardEvent;
    if (!key.shiftKey && !key.isComposing) {
      key.preventDefault();
      void this.send();
    }
  }

  toggle(): void {
    this.open.update((value) => !value);
    if (this.open()) {
      void this.loadModels();
      setTimeout(() => this.input()?.nativeElement.focus());
      this.scroll();
    } else {
      setTimeout(() => this.launcher()?.nativeElement.focus());
    }
  }

  async send(text = this.question): Promise<void> {
    text = text.trim();
    const topic = this.topic();
    const employeeTopic = topic === 'employees';
    if (
      !text ||
      text.length > 2000 ||
      this.pending() ||
      (employeeTopic && !this.employeeAccess()) ||
      (!employeeTopic && (this.modelsLoading() || !this.models.config()))
    )
      return;
    this.question = '';
    this.error.set('');
    this.pending.set(true);
    const provider = this.models.provider();
    const config = this.models.config();
    const modelLabel = employeeTopic
      ? 'MCP · Nhân sự'
      : provider === 'groq'
        ? `Groq · ${config!.groqModel}`
        : `Local · ${config!.localModel}`;
    this.status.set(
      employeeTopic
        ? 'Đang tra cứu nhân viên trong database…'
        : topic === 'secops'
          ? 'Đang tra cứu tài liệu và tạo câu trả lời…'
          : 'Đang tìm khóa học phù hợp…',
    );
    const replyId = this.nextId++;
    this.conversations.update((items) => [
      ...items.filter((item) => item.topic !== topic),
      ...items.filter((item) => item.topic === topic).slice(-30),
      { id: this.nextId++, role: 'user', text, courses: [], sources: [], topic },
      { id: replyId, role: 'assistant', text: '', courses: [], sources: [], topic, modelLabel },
    ]);
    this.controller = new AbortController();
    this.scroll();
    const slug =
      /^\/(?:courses|learn|checkout)\/([a-z0-9-]+)(?:[?#]|$)/.exec(this.router.url)?.[1] ?? null;
    try {
      await this.chat.ask(
        text,
        topic === 'courses' ? slug : null,
        this.controller.signal,
        (event) => {
          if (event.event === 'status')
            this.status.set((event.data as { message: string }).message);
          if (event.event === 'answer' || event.event === 'answer_delta') {
            this.conversations.update((items) =>
              items.map((item) =>
                item.id === replyId ? { ...item, ...applyAnswerEvent(item, event) } : item,
              ),
            );
          }
          if (event.event === 'courses')
            this.update(replyId, { courses: event.data as ChatCourse[] });
          if (event.event === 'sources')
            this.update(replyId, { sources: event.data as ChatSource[] });
          if (event.event === 'done')
            this.update(replyId, {
              answerMode: (event.data as Pick<Message, 'answerMode'>).answerMode,
              fallbackReason: (event.data as Pick<Message, 'fallbackReason'>).fallbackReason,
              engine: (event.data as Pick<Message, 'engine'>).engine,
            });
          this.scroll();
        },
        topic,
        provider,
      );
    } catch (error) {
      this.update(replyId, { text: '', courses: [], sources: [], streaming: false });
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        this.error.set(error instanceof Error ? error.message : 'Chưa kết nối được trợ lý.');
        this.question = text;
      }
    } finally {
      this.conversations.update((items) =>
        items.filter((item) => item.id !== replyId || item.text || item.courses.length),
      );
      this.pending.set(false);
      this.status.set('');
      this.scroll();
    }
  }

  private update(id: number, changes: Partial<Message>): void {
    this.conversations.update((items) =>
      items.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    );
  }

  private scroll(): void {
    requestAnimationFrame(() => {
      const element = this.log()?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    });
  }

  ngOnDestroy(): void {
    this.controller?.abort();
  }
}
