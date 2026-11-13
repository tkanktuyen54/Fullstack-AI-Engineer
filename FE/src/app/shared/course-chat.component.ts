import {
  Component,
  ElementRef,
  OnDestroy,
  computed,
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

interface Message {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  courses: ChatCourse[];
  sources: ChatSource[];
  topic: ChatTopic;
  answerMode?: 'course' | 'generated' | 'extractive' | 'not_found' | 'blocked';
  streaming?: boolean;
}

@Component({
  selector: 'app-course-chat',
  imports: [FormsModule, RouterLink, CurrencyPipe],
  templateUrl: './course-chat.component.html',
  styleUrl: './course-chat.component.css',
})
export class CourseChatComponent implements OnDestroy {
  readonly auth = inject(AuthService);
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
  readonly topic = signal<ChatTopic>('courses');
  private readonly conversations = signal<Message[]>([]);
  readonly messages = computed(() =>
    this.conversations().filter((item) => item.topic === this.topic()),
  );
  readonly prompts = computed(() =>
    this.topic() === 'secops'
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

  selectTopic(topic: ChatTopic): void {
    if (this.pending()) return;
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
      setTimeout(() => this.input()?.nativeElement.focus());
      this.scroll();
    } else {
      setTimeout(() => this.launcher()?.nativeElement.focus());
    }
  }

  async send(text = this.question): Promise<void> {
    text = text.trim();
    if (!text || text.length > 2000 || this.pending()) return;
    this.question = '';
    this.error.set('');
    this.pending.set(true);
    const topic = this.topic();
    this.status.set(
      topic === 'secops'
        ? 'Đang tra cứu tài liệu và tạo câu trả lời…'
        : 'Đang tìm khóa học phù hợp…',
    );
    const replyId = this.nextId++;
    this.conversations.update((items) => [
      ...items.filter((item) => item.topic !== topic),
      ...items.filter((item) => item.topic === topic).slice(-30),
      { id: this.nextId++, role: 'user', text, courses: [], sources: [], topic },
      { id: replyId, role: 'assistant', text: '', courses: [], sources: [], topic },
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
            });
          this.scroll();
        },
        topic,
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
