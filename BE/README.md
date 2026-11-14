# Tuyen Pham - Tư vấn khóa học · API

Backend Java 21 / Spring Boot 4, JDBC và MySQL. Giữ cấu trúc `core + modules` của project gốc.

```text
src/main/java/com/bigproject/
├── BigProjectApplication.java
├── core/
│   ├── config/       # OpenAPI
│   ├── exception/    # Lỗi API, không trả lỗi SQL ra client
│   ├── security/     # Spring Security, session, CSRF, BCrypt
│   └── util/
└── modules/
    ├── auth/         # Đăng ký, đăng nhập, thông tin tài khoản
    ├── course/       # Danh sách, tìm kiếm, chi tiết, xem thử
    ├── enrollment/   # Đơn hàng demo và khóa học đã đăng ký
    ├── learning/     # Kiểm tra quyền xem bài học, lưu tiến độ
    ├── user/         # Repository tài khoản; giữ API cũ, chỉ cho ADMIN
    └── home/
```

Mỗi tính năng dùng `controller → service → repository`; DTO và entity nằm trong module tương ứng.

## Chạy bằng Docker

Đội BE quản lý `Dockerfile`, `compose.yaml` và MySQL ngay trong thư mục `BE`, không cần mã nguồn FE. Từ thư mục `BE`:

```powershell
# Build image backend
docker compose build backend

# Chạy backend và MySQL
docker compose up -d

# Build lại và chạy khi sửa code
docker compose up -d --build backend

# Xem log hoặc dừng các dịch vụ BE
docker compose logs -f backend
docker compose stop
```

API Docker: `http://localhost:8081`. Swagger Docker: `http://localhost:8081/swagger-ui.html`. MySQL: `localhost:3307`.

Copy `.env.example` thành `.env` trong `BE` nếu cần đổi cổng hoặc mật khẩu. Giữ tên project `khoa` trong Compose để dùng tiếp volume `khoa_khoa_mysql`; dữ liệu hiện tại vẫn được giữ khi chuyển từ Compose chung sang Compose BE.

Khi FE chạy trên máy khác, đặt `BACKEND_BIND_ADDRESS=0.0.0.0` trong `BE/.env` rồi chạy lại `docker compose up -d backend`. Đội FE dùng địa chỉ IP hoặc domain của máy BE trong `BACKEND_URL`; hai đội không cần chia sẻ Docker network. Với Docker Engine trên Linux, cũng dùng địa chỉ bind này nếu FE cùng máy truy cập API qua `host.docker.internal`.

## Chạy để phát triển

Khởi động MySQL từ thư mục `BE`: `docker compose up -d mysql`.

```powershell
$env:JAVA_HOME = 'C:\duong-dan\jdk-21'
.\mvnw.cmd spring-boot:run
```

macOS/Linux: `./mvnw spring-boot:run` với `JAVA_HOME` trỏ tới JDK 21.

API: `http://localhost:8080`. Swagger: `http://localhost:8080/swagger-ui.html`.

Swagger hiển thị liên kết **Download OpenAPI Document** ngay dưới tiêu đề để tải spec đang được sinh từ các controller:

- JSON: `http://localhost:8080/v3/api-docs?download=true` → `tuyen-pham-openapi.json`.
- YAML: `http://localhost:8080/v3/api-docs.yaml?download=true` → `tuyen-pham-openapi.yaml`.

Đường dẫn không có `?download=true` vẫn trả spec trực tiếp. Profile `prod` tắt cả Swagger và các endpoint OpenAPI.

Chưa có tài khoản mặc định. Tạo tài khoản tại `http://localhost:4200/register`. Để thử API đăng nhập ngay trong Swagger, gọi `GET /api/auth/csrf`, rồi gọi `POST /api/auth/register` hoặc `POST /api/auth/login`. Swagger tự gửi header CSRF từ cookie. Gọi lại endpoint CSRF sau mỗi lần đăng nhập/đăng xuất trước khi thực hiện POST tiếp theo.

Tham khảo: [springdoc OpenAPI JSON/YAML](https://springdoc.org/getting-started.html), [cấu hình Swagger UI](https://springdoc.org/ui-properties.html).

## Cấu hình

| Biến môi trường | Mặc định khi phát triển |
| --- | --- |
| `SPRING_PROFILES_ACTIVE` | `dev` |
| `DATABASE_URL` | `jdbc:mysql://localhost:3307/khoa?useUnicode=true&characterEncoding=UTF-8&serverTimezone=UTC` |
| `DATABASE_USERNAME` | `khoa` |
| `DATABASE_PASSWORD` | `khoa_local_password` |
| `PORT` | `8080` |
| `COOKIE_SECURE` | `false` ở dev, `true` ở prod |
| `DEMO_CHECKOUT_ENABLED` | `true` ở dev, `false` ở prod |

Flyway tự tạo schema và dữ liệu khóa học mẫu khi khởi động. Migration nằm ở `src/main/resources/db/migration`. Khi đã chạy migration, thêm file migration phiên bản mới để thay đổi dữ liệu/schema; không sửa migration đã áp dụng.

## API

API nhân viên và phiếu tạo/sửa qua duyệt: xem [Employee API](docs/employees.md), gồm payload mẫu, endpoint, phân quyền HR/HR_APPROVER và quy trình kiểm thử.

| Method | Endpoint | Quyền |
| --- | --- | --- |
| GET | `/api/courses?q=&category=` | Công khai |
| GET | `/api/courses/{slug}` | Công khai; không trả URL video bài học |
| GET | `/api/courses/{slug}/preview` | Công khai, bài xem thử |
| GET | `/api/config` | Công khai, trạng thái checkout demo |
| GET | `/api/auth/csrf` | Công khai, lấy cookie CSRF |
| POST | `/api/auth/register` | Công khai + CSRF; `{name,email,password}` |
| POST | `/api/auth/login` | Công khai + CSRF; `{email,password}` |
| POST | `/api/auth/logout` | Đăng nhập + CSRF |
| GET | `/api/auth/me` | Đăng nhập |
| GET | `/api/enrollments` | Đăng nhập |
| POST | `/api/enrollments/{slug}/demo-checkout` | Đăng nhập + CSRF; demo phải bật |
| GET | `/api/learning/{slug}/lessons/{id}` | Đã đăng ký đúng khóa học |
| GET | `/api/learning/{slug}/progress` | Đã đăng ký đúng khóa học |
| POST | `/api/learning/{slug}/lessons/{id}/complete` | Đã đăng ký đúng khóa học + CSRF |
| GET | `/api/media/lessons/{id}` | Công khai với bài xem thử; các bài khác phải đăng nhập và đăng ký đúng khóa; hỗ trợ Range |

Đăng ký thành công đồng thời đăng nhập. Backend lưu phiên bằng cookie `JSESSIONID` HttpOnly; không lưu token vào localStorage. Client lấy lại `/api/auth/csrf` sau login/register/logout, và gửi cookie `XSRF-TOKEN` qua header `X-XSRF-TOKEN` khi POST. Angular thực hiện phần header tự động khi gọi cùng origin; dev proxy và Nginx đã được cấu hình để giữ cùng origin.

Giá đơn hàng lấy từ database, không nhận giá từ client. Khóa duy nhất và transaction ngăn tạo đơn trùng. Endpoint video và endpoint media kiểm tra người học và đơn đăng ký; endpoint bài học còn kiểm tra quan hệ bài học/khóa học. Clip Flower (MDN, CC0) được đóng gói tại `src/main/resources/media`, có file nguồn/giấy phép đi kèm; mọi bài mẫu hiện dùng chung clip minh họa.

## Format code

Dùng Spotless với Google Java Format (GOOGLE), thụt lề Java 2 dấu cách, thống nhất import và xuống dòng. `pom.xml` cũng dùng 2 dấu cách. Cấu hình formatter được cố định phiên bản trong `pom.xml`.

```powershell
.\mvnw.cmd spotless:apply
.\mvnw.cmd spotless:check
```

`spotless:apply` sửa định dạng, `spotless:check` chỉ kiểm tra. `mvnw verify` cũng kiểm tra format. Không tự format lại các SQL migration đã chạy vì Flyway kiểm tra checksum của chúng.

## Kiểm thử và đóng gói

```powershell
.\mvnw.cmd test
.\mvnw.cmd package
```

Test dùng H2 ở chế độ MySQL, chạy độc lập với MySQL thật. Từ thư mục gốc, `node scripts/smoke.mjs` kiểm tra API trên MySQL đang chạy; script tạo một tài khoản kiểm thử mới và một đơn demo, không xóa dữ liệu hiện có.

Nếu máy Windows báo lỗi chứng chỉ Maven `PKIX`, có thể dùng kho chứng chỉ Windows cho lệnh build (không tắt xác thực TLS):

```powershell
$env:MAVEN_OPTS = '-Djavax.net.ssl.trustStoreType=Windows-ROOT -Djavax.net.ssl.trustStore=NONE'
```

<a id="employee-mcp"></a>

## MCP tra cứu nhân viên

MCP server dùng [MCP Java SDK](https://java.sdk.modelcontextprotocol.io/latest/server/), transport Streamable HTTP stateless tại `POST /api/mcp/employees`. Có thể truy cập trực tiếp API `http://127.0.0.1:8081/api/mcp/employees` hoặc qua proxy frontend. Server hỗ trợ `initialize`, `tools/list`, `tools/call`; không hỗ trợ luồng GET SSE dài hạn.

Ba tool chỉ đọc database đang được backend sử dụng:

- `count_employees`: tổng số hồ sơ được duyệt, nhận `status` và `department` tùy chọn.
- `search_employees`: tìm theo `query` (tên/mã; rỗng để liệt kê), có `status`, `department`, `page` tùy chọn. Mỗi trang tối đa 10 hồ sơ, trang từ 1 đến 1000; trả `total` để biết có thêm kết quả.
- `get_employee`: đọc thông tin công việc theo `employeeCode`, ví dụ `EMP-000001`. Ưu tiên mã khớp chính xác; nếu không có mới bỏ số 0 thừa ở đầu theo định dạng mã tự sinh, ví dụ `EMP-0000050` có thể tra được `EMP-000050`. Kết quả luôn hiển thị mã thực tế trong database. Không tìm thấy trả lỗi tool, không tạo thông tin thay thế.

`status` nhận `Active`, `Suspended`, `Terminated` hoặc bỏ trống để tính tất cả. `department` khớp toàn bộ tên phòng ban, không phân biệt chữ hoa/thường. Các truy vấn dùng SQL cố định và bind tham số; không nhận SQL từ model/client. Đơn tạo/sửa đang chờ duyệt chưa được tính vào hồ sơ hiện hành. Không thêm bảng hay thay đổi dữ liệu khi gọi tool.

Mỗi lần gọi tool đều truy vấn database hiện tại qua JDBC; không đọc một bản JSON danh sách nhân viên và không cache kết quả hồ sơ. Nhân viên mới được duyệt hoặc cập nhật đã commit sẽ được truy vấn ở lần hỏi kế tiếp, không cần training, export JSON hay khởi động lại backend. Các file kết quả demo/seed chỉ ghi nhận lần tạo dữ liệu, không tham gia luồng trả lời. Vector database không cần thiết cho đếm hoặc tìm mã chính xác; cần kiểm tra đúng mã và đúng trạng thái duyệt trước.

Tool trả `employeeCode`, `fullName`, `department`, `position`, `status`, `workEmail`, `workPhone`. Chỉ lấy liên hệ loại `Work` được đánh dấu chính. Nếu không có, các trường liên hệ là `null`; không lấy liên hệ cá nhân thay thế. Không trả CCCD, mã số thuế, ngày sinh, địa chỉ hoặc người liên hệ khẩn cấp. Giá trị các trường nhân viên phải được client xử lý như dữ liệu, không phải chỉ dẫn.

Phân quyền giống API nhân viên: cần đăng nhập với `HR`, `HR_APPROVER` hoặc `ADMIN`. Đăng ký tài khoản thông thường chỉ có `STUDENT`; không tự cấp quyền nhân sự. Quản trị viên quản lý quyền qua bảng `account_role` theo quy trình hiện có, rồi người dùng đăng nhập lại. `/api/auth/me`, login và register trả thêm mảng `roles` để giao diện hiển thị mục Nhân sự. Backend vẫn kiểm tra quyền cho mỗi request, kể cả khi client tự gửi `topic: "employees"`.

### Kết nối MCP client bằng STDIO

Cần Node.js 24.15+ và backend đang chạy. Adapter [scripts/employee-mcp.mjs](../scripts/employee-mcp.mjs) đăng nhập bằng tài khoản của người dùng, giữ cookie/CSRF trong bộ nhớ và chuyển JSON-RPC STDIO sang MCP HTTP. Adapter không kết nối trực tiếp MySQL. Nó chỉ ghi thông điệp MCP ra stdout; lỗi khởi động được ghi ra stderr với nội dung cố định.

Cấu hình MCP client, thay đường dẫn và các placeholder bằng cấu hình riêng của máy:

```json
{
  "mcpServers": {
    "employees": {
      "command": "node",
      "args": ["/absolute/path/to/project/scripts/employee-mcp.mjs"],
      "env": {
        "EMPLOYEE_MCP_URL": "http://127.0.0.1:8081",
        "EMPLOYEE_MCP_EMAIL": "<EMAIL_TAI_KHOAN_HR>",
        "EMPLOYEE_MCP_PASSWORD": "<MAT_KHAU>"
      }
    }
  }
}
```

Giữ cấu hình chứa mật khẩu ngoài Git, hoặc truyền các biến môi trường qua cơ chế lưu secret của MCP client. URL không có path, query hay thông tin đăng nhập. Adapter chỉ cho HTTP ở loopback; dùng HTTPS khi kết nối máy khác. Phiên đăng nhập hết hạn hoặc quyền bị thay đổi thì khởi động lại adapter sau khi đăng nhập/cấp quyền theo quy trình của hệ thống.

Ví dụ tool call:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "count_employees",
    "arguments": {"department": "IT", "status": "Active"}
  }
}
```

Client HTTP trực tiếp cần cookie `JSESSIONID`, cookie `XSRF-TOKEN`, header `X-XSRF-TOKEN` và `Accept: application/json, text/event-stream`. Lấy CSRF trước login và lấy lại sau login. Các request tiếp theo gửi `MCP-Protocol-Version` theo kết quả `initialize`. Giữ CSRF bật cho MCP vì endpoint dùng phiên đăng nhập.

Server kiểm tra Host/Origin, mặc định cho localhost, 127.0.0.1 và host nội bộ `backend:8080`. Khi triển khai ở tên miền khác, đặt `EMPLOYEE_MCP_ALLOWED_HOSTS` và `EMPLOYEE_MCP_ALLOWED_ORIGINS` (danh sách ngăn bằng dấu phẩy) trong môi trường backend/Compose, ví dụ thêm `api.example.com` và `https://app.example.com`.

Trong ô chat, chủ đề `employees` gọi cùng lớp tool ngay trong backend sau khi kiểm tra quyền; không vòng qua HTTP và không gửi dữ liệu nhân sự đến dịch vụ AI. Luồng này dùng câu lệnh đếm/tìm/đọc có giới hạn thay vì suy đoán truy vấn SQL từ ngôn ngữ tự nhiên. Mẫu câu và cách sử dụng có ở [README gốc](../README.md#tra-cứu-nhân-sự-qua-chat-và-mcp).

Kiểm thử MCP protocol trên HTTP thật, phân quyền, CSRF, bộ lọc, dữ liệu riêng tư và ô chat trong bộ test Maven. Adapter có test riêng từ thư mục gốc:

```bash
node --test scripts/employee-mcp.test.mjs
```
