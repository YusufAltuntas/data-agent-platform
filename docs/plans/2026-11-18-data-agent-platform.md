# data-agent-platform: uygulama planı

> Bu dosya uygulama oturumunun çalışma kurallarının, görev listesinin ve oturum boyunca tutulan kayıtların (karar günlüğü, engeller, sabah raporu) sahibidir. Tasarım kararları `docs/design.md`'de yaşar. Bu dosya onları tekrar etmez, numarasıyla (K1–K23, §13) atıf yapar.

## Oturumun çalışma mantığı

### Akış

1. **Kullanıcı bilgisayarın başındayken:**
   1. Oturum `docs/design.md` §13'teki "Ön koşullar ve kurulum" adımlarını yapar: eksik araçları kurar, repoyu klonlar, `.env`'i hazırlar ve kontrol komutlarının çıktılarını gösterir. Yönetici izni, lisans onayı, tarayıcıda giriş ve API anahtarını yapıştırma işlerini kullanıcı yapar; oturum her birinde ne yapması gerektiğini tek cümleyle söyler ve bekler.
   2. Oturum aşağıdaki "Görevler" bölümünü `docs/design.md` §13'ten, bölümün başındaki alan listesine göre kendisi yazar ve kullanıcının onayına sunar. Onaydan sonra planı `docs: add tasks to the implementation plan` mesajıyla commit'ler.
   3. Kullanıcı, uyumadan önce oturumun izin modunu gece soru sormadan çalışabileceği moda alır.
2. **Gece:** Kullanıcı uyur. Oturum yalnız onaylı planı uygular, plana yeni görev eklemez ve hiçbir şey kurmaz. Bir görevi bölmek ya da atlamak gerekirse bu bir Ruling'dir (bkz. Kayıt).

### Orkestrasyon

Gece oturumu orkestratördür. Kodu kendisi yazmaz; görevleri alt agent'lara verir ve sonuçları kendisi doğrular. Yöntem `subagent-driven-development` skill'i; repoda `.claude/skills/subagent-driven-development/SKILL.md` olarak durur ve oturum onu bu dosyadan okur. Aşağıdaki kurallar bu proje için skill'in önüne geçer.

- **Dal:** `main` üzerinde doğrudan çalışılır, worktree açılmaz. Gerekçe: git dışı `.env`, `deploy/secrets/` ve kind cluster'ının durumu worktree'de olmaz. Bu madde, skill'in "main'de başlamadan önce sor" adımının onayıdır.
- **Görev biçimi:** Her görev `### Task N: <ad>` başlığıyla yazılır (N = 0, 1, 2, …). Her görevin ilk satırı bağlı olduğu kilometre taşını söyler (design §13, M0–M8). Bir M birden çok göreve bölünebilir.
- **Görev brief'i:** Alt agent'a görev skill'in kendi script'iyle verilir: `.claude/skills/subagent-driven-development/scripts/task-brief docs/plans/2026-11-18-data-agent-platform.md N` (repo kökünden). Script başlığı `Task N` diye arar; `Tn` gibi başka bir biçim bulunamaz.
- **Global kısıtlar:** repodaki `CLAUDE.md`, `docs/design.md`'deki kararlar tablosu (K1–K23) ve bölüm 14 (Kapsam dışı). Reviewer'a görevle ilgili kararlar numarasıyla ve metniyle aynen verilir. **Öncelik:** K19 (kod yorumları ve docstring'ler İngilizce) geçerlidir; kullanıcının global Türkçe yorum kuralı bu repoda uygulanmaz. Bu cümle her reviewer brief'ine yazılır, yoksa reviewer İngilizce yorumları hata sayar.
- **Modeller:** Tüm alt agent'lar (uygulayıcı, task reviewer, fix-loop, re-review) **`model: opus`** ile açılır. Skill'in "en ucuz yeterli model" önerisi bu projede geçersiz. Yalnız en sondaki whole-branch review `fable` ile yapılabilir. Model her dispatch'te açıkça yazılır.
- **Görev başına sınır:** Bir görev 3 fix döngüsünde kabul ölçütlerini geçmezse ya da 90 dakikayı aşarsa durum Engeller'e yazılır ve ona bağımlı olmayan sıradaki göreve geçilir.

### Ortam (yerel Windows 11, design K21)

- Oturum Windows'ta, Claude Code içinde çalışır; Bash aracı Git Bash'tir. Çalışma klasörü repo köküdür: `C:\Users\Yusuf Altuntaş\Desktop\data-agent-platform` (design §13). Komutlar repo kökünden çalıştırılır.
- Repo kökündeki `CLAUDE.md` oturum başında okunur.
- Script'ler ve yapılandırma dosyaları LF satır sonuyla yazılır (`.gitattributes`). Shebang'li her script'e çalıştırma izni git'te verilir (`git update-index --chmod=+x`).
- Python komutları her yerde `uv run` ile çağrılır. Container içi mutlak yol geçen `docker` ve `kubectl` çağrılarında `MSYS_NO_PATHCONV=1` kullanılır (K21).
- Oturumun kendi doğrulaması `curl` ile yapılır. Tarayıcı kontrolü kullanıcıya bırakılır: Windows'taki tarayıcıdan `*.localhost` adreslerine bakılır (K16; 2026-11-19'a kadar `*.localtest.me` idi, tamamlanmış görev metinlerinde eski adres durur).
- Host'un 80 portu doluysa oturum `publicPort`'u 8080 yapar (design K16, §10) ve bunu Karar günlüğüne yazar. Port'u tutan Windows servisini durdurmaz.
- Oturum başında `task-brief` script'inin Git Bash'te çalıştığı denenir. Bu kontrol kullanıcı başındayken yapılır.

### Commit

- Görevin ana commit'ini uygulayıcı atar ve bu plandaki commit mesajını aynen kullanır.
- Fix-loop commit'leri Conventional Commits biçiminde ve İngilizce olur.
- Görevin `- [ ] Tamamlandı` kutusunu orkestratör işaretler. Bunu ancak kabul ölçütlerini **kendisi** çalıştırıp çıktısını gördükten sonra yapar ve ayrı bir `docs: mark Task N done in plan` commit'iyle kaydeder. Aynı commit'te Sabah raporu da o göreve göre güncellenir.
- **Commit öncesi kontrol (orkestratör):**
  - `.env`, `deploy/secrets/`, `runs/`, `.superpowers/`, `node_modules/` ve `frontend/dist/` git'e girmiyor.
  - Gerçek bir anahtar, parola ya da token hiçbir dosyada yok. Kapsam: values dosyaları, `deploy/keycloak/realm-export.json`, test fixture'ları, CI workflow'u. Parolalar `.env`'den gelir (design §5).
  - README'ye, bu plana ya da `docs/design.md`'ye yazılan her ölçüm sayısının bir `runs/` klasöründe ya da `eval/results/` özetinde karşılığı var (design K23).

### Paralellik

- Repoya aynı anda tek uygulayıcı yazar.
- **Uzun işler arka planda:** Docker image build'leri, `make up` (kind kurulumu ve Helm kurulumları) ve testcontainers'lı integration testleri. Orkestratör bunları ilgili script hazır olduktan sonra arka planda başlatır. Beklerken ona bağımlı olmayan sıradaki görev yürür. Örnek: M5'te cluster ayağa kalkarken M6'nın metrik kodu yazılabilir.
- **Salt okuma araştırması** ayrı bir alt agent'ta paralel yapılabilir. Örnekler: LiteLLM'in Langfuse `metadata` anahtarları, Keycloak realm import biçimi, Traefik chart değerleri. Kaynak dokümanın sürümü Karar günlüğüne yazılır.

### Kayıt

- Skill'in ledger'ı (`.superpowers/sdd/`, git dışı) kurtarma haritasıdır.
- Kullanıcıyı ilgilendiren her `Ruling` ayrıca aşağıdaki **Karar günlüğü**ne yazılır.
- Her engel **Engeller**'e yazılır.
- Tasarımdan sapma gerekirse (bir K kararını değiştirmek) bu da bir Ruling'dir. `docs/design.md` sessizce değiştirilmez: sapma Karar günlüğüne yazılır, design.md'deki ilgili satır aynı commit'te güncellenir.

### Durma koşulları

Kullanıcı uyuyor, soru sorulmaz. Şu durumlarda o adım yapılmaz, Engeller'e yazılır ve sıradaki bağımsız göreve geçilir:

- Geri alınamaz ya da yıkıcı bir işlem gerekiyorsa. Örnekler: projenin oluşturmadığı Docker image'larını, volume'larını ya da cluster'larını silmek; `git reset --hard` ya da geçmişi yeniden yazmak.
- Güvenlik açısından hassas bir eylem gerekiyorsa. Örnekler:
  - sistem ayarı değiştirmek, `sudo`
  - Docker Desktop ayarları, Windows servisleri, güç ayarları
  - sisteme program ya da paket kurmak (`winget`, global `npm -g`, yeni bir CLI). Kurulum yalnız 1. aşamada, kullanıcı başındayken yapılır (bkz. Akış); gece bir araç eksik çıkarsa engel.
- Dışarıya etkisi olan bir işlem gerekiyorsa: push, merge, GitHub'da repo ya da ayar değiştirmek, yayın.

**Serbest olanlar:**
- Proje bağımlılıkları: `uv sync`, uv'nin Python indirmesi, `npm install` / `npm ci`, `helm repo add` / `helm dependency update`, `docker pull` / `docker build`.
- Projenin kendi kind cluster'ını (`make down`) silip yeniden kurmak.

### Kaynaklar ve maliyet

- **Bellek:** Docker Desktop'ın payı (en az 6 GB, design §13). Cluster hedefi 4 GB'ın altında (design §10). Pod'lar OOM olursa önce `requests` ve `limits` ayarlanır, bileşen kapsam dışı bırakılmaz. Ölçülen kullanım (`docker stats`) ve yapılan ayar Karar günlüğüne yazılır.
- **Abonelik kotası:** Orkestratör ve alt agent'lar aynı aboneliği kullanır. Gereksiz alt agent açılmaz, büyük çıktı okunmaz. Büyük dosya ve log okumayı alt agent'lar yapar ve orkestratöre dosya yolunu döner. Kota ya da oturum yarıda biterse Sabah raporu son tamamlanan göreve kadar dolu kalır (bkz. Commit).
- **API maliyeti:** Gerçek model varsayılan olarak kapalıdır (design K22). Testler, CI ve `make smoke` `FakeProvider` ile çalışır. Gece yalnız M5'in sonundaki tek elle doğrulama koşusu `REAL_LLM=1` ile yapılır; eval ertesi güne kalır (design §13, M9). Gece boyunca toplam API harcaması **5 $** ile sınırlı. Sınıra yaklaşılırsa gerçek model çağrıları durur ve durum Engeller'e yazılır. Harcama LiteLLM'in kayıtlarından okunur ve Sabah raporuna yazılır.

### Bitiş

- Gece kapsamı M0–M8'dir (design §13). M9 yapılmaz.
- Skill'in final whole-branch review'u yapılır.
- `finishing-a-development-branch` adımı **uygulanmaz**: merge ve push yok.
- Sabah raporu son haline getirilir.

## Görevler

> Oturum bu bölümü `docs/design.md` §13'ten, oradaki sırayla (M0–M8) yazar. Her adımın kodunu tek tek yazmaz; görev, bir alt agent'ın design.md'ye bakarak uygulayabileceği ayrıntıda olur. Her görevde şunlar bulunur:
> - `### Task N: <ad>` başlığı ve bağlı olduğu M
> - amaç ve dokunulacak dosyalar
> - görevle ilgili K kararları (numarasıyla)
> - kabul ölçütleri: çalıştırılacak komutlar ve beklenen çıktı
> - commit mesajı
> - `- [ ] Tamamlandı`
>
> Plan, kullanıcı uyumadan önce onaydan geçer (bkz. Akış).

### Ortak kurallar (orkestratör her brief'le birlikte verir)

- **Python:** 3.13. uv projesi `backend/` altındadır (`backend/pyproject.toml`, paket `dap`). Her şey repo kökünden `make` hedefleriyle çağrılır.
- **Makefile:** `SHELL := bash`, yalnız göreli yollar. Repo yolu boşluk ve ASCII dışı karakter içerir (`C:\Users\Yusuf Altuntaş\...`); mutlak yol üreten her kullanım tırnaklanır.
- **Kalite kapısı:** `make lint` = `ruff check` + `ruff format --check` + `mypy` (strict). `make test` = pytest, unit ve integration birlikte. Integration testleri testcontainers ile gerçek Postgres, Redis ve RabbitMQ kullanır; container'lar oturum kapsamlı fixture'dır. Her görev `make lint test` yeşilken biter.
- **Senkron / asenkron (K21):** API async'tir (`asyncpg`). Worker ve `agent` kütüphanesi senkrondur (`psycopg`, senkron `openai` istemcisi). Host testlerinde Celery `solo` havuzuyla koşar.
- **Ayarlar:** Ortam değişkeni adlarının tek sahibi `backend/dap/settings.py`'dir (pydantic-settings). Yeni bir sır ekleyen görev `.env.example`'ı da günceller. Uygulama ayarları yalnız süreç ortamından okur, `.env` dosyasını kendisi yüklemez; `.env`'i `scripts/secrets.sh` ve Makefile kullanır. Alt agent'lar `.env`'in değerlerini hiçbir çıktıya, log'a ya da dosyaya yazmaz.
- **Test önce yazılır.** Kabul ölçütlerindeki her komut, döndürdüğü çıktıyla birlikte görev raporunda yer alır.
- **Gerçek model çağrısı yok (K22).** İstisnalar yalnız Task 9'un 3. maddesi ve Task 11'in sonundaki elle koşudur.
- **Kapsam:** Görevde yazmayan şey eklenmez; design §14 yapılmaz. Bir kilometre taşının son görevi README taslağında ilgili bölümü günceller.
- **Araç sürümleri (kurulu):** kind 0.33.0 (node image Kubernetes 1.37), kubectl 1.37.2, Helm 4.3.2, kubeconform 0.8.0, GNU make 4.4.1, jq 1.8.2, uv 0.13.9, Node.js 24.15.0, Docker 27.5.1.

### Task 0: Proje iskeleti

**Kilometre taşı:** M0

**Amaç:** Araç zinciri ve boş paket. Sonraki her görev bu kapının (`make lint test`) içinde çalışır.

**Dosyalar:** `backend/pyproject.toml`, `backend/.python-version`, `backend/dap/__init__.py`, `backend/tests/unit/test_placeholder.py`, `Makefile`, `.env.example`, `README.md`

**İçerik:**
- `pyproject.toml`: ruff (lint + format), mypy strict, pytest (`--strict-markers`, `integration` marker'ı), geliştirme bağımlılıkları ayrı grupta.
- Makefile hedefleri: `lint`, `test`, `help`. Diğer hedefleri (`up`, `down`, `smoke`, `helm-lint`, `frontend-check`, `ci`) onları dolduran görev ekler; boş yer tutucu hedef yazılmaz.
- `.env.example`: `.env` ile aynı anahtarlar, değerler boş, her grubun üstünde bir satır açıklama. Anahtarlar: `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `PUBLIC_PORT`, `DAP_ALICE_PASSWORD`, `DAP_BOB_PASSWORD`, `DAP_CAROL_PASSWORD`, `DAP_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, `DS_SALES_RO_PASSWORD`, `DS_HR_RO_PASSWORD`, `RABBITMQ_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `LITELLM_MASTER_KEY`, `DAP_FERNET_KEY`.
- README taslağı (İngilizce): ne olduğu ("personal project, local Kubernetes (kind) deployment", design §1), mimari diyagramı (design §4), "Development" (make hedefleri; Windows'ta `make` Git Bash'ten çalıştırılır), "Production gaps" (design §10 listesi). AI bölümü yok (K20).

**Kararlar:** K19, K20, K21

**Kabul ölçütleri:**
- `make lint` → çıkış kodu 0.
- `make test` → çıkış kodu 0, `1 passed`.
- Yer tutucu test silinip `make test` çalıştırılınca çıkış kodu 0 değildir (pytest test bulamazsa hata verir); deneme sonrası test geri konur.

**Commit:** `chore: scaffold backend package, tooling and Makefile`

- [x] Tamamlandı

### Task 1: dap veritabanı modelleri ve migration

**Kilometre taşı:** M1

**Amaç:** Uygulamanın kendi veritabanı şeması (design §5, `dap` veritabanı) ve bağlantı katmanı.

**Dosyalar:** `backend/dap/settings.py`, `backend/dap/db/models.py`, `backend/dap/db/session.py`, `backend/alembic.ini`, `backend/dap/db/migrations/`, `backend/tests/conftest.py`, `backend/tests/integration/test_migrations.py`

**İçerik:**
- SQLAlchemy 2.0 tipli modeller: `teams`, `memberships`, `datasets`, `dataset_grants`, `runs`, `run_events`, `audit_log`. Kısıtlar: `memberships` pk (`team_id`, `email`), `role` ve `runs.status` için check, `run_events` tekil (`run_id`, `seq`), yabancı anahtarlar, `runs` (`team_id`, `created_at`) indeksi. `runs.attempts` varsayılanı 0.
- `session.py`: aynı veritabanı ayarından async engine (asyncpg, API için) ve senkron engine (psycopg, worker için).
- Alembic: tek başlangıç migration'ı, senkron sürücüyle çalışır.
- `conftest.py`: oturum kapsamlı Postgres testcontainer fixture'ı. Sonraki görevler Redis ve RabbitMQ fixture'larını buraya ekler.

**Kararlar:** K11 (`attempts`), K12 (`seq`, `attempt`), K21

**Kabul ölçütleri:**
- `make lint test` → 0.
- Migration testi: boş veritabanında `upgrade head` yedi tabloyu oluşturur; modellerle migration arasında fark yoktur (`alembic check` temiz); `downgrade base` hatasız döner.

**Commit:** `feat(db): add dap schema models and initial migration`

- [x] Tamamlandı

### Task 2: Sentetik veri setleri, salt-okuma rolleri ve seed

**Kilometre taşı:** M1

**Amaç:** `datasets` veritabanı (K18), veri seti başına LOGIN rolü (K9'un 1. katmanı) ve uygulama seed'i (design §5).

**Dosyalar:** `backend/dap/db/datasets.py`, `backend/dap/db/seed.py`, `backend/dap/db/bootstrap.py`, `backend/dap/crypto.py`, `backend/tests/integration/test_datasets.py`, `backend/tests/integration/test_seed.py`

**İçerik:**
- Faker ve sabit seed ile üretim. `sales` şeması: `customers`, `products`, `orders`, `order_items`, yaklaşık 5.000 sipariş, sipariş tarihleri sabit 2025-01-01 – 2026-10-31 aralığında (demo sorusundaki "last quarter" dolu kalır). `hr` şeması: `departments`, `employees`, `salaries`.
- Roller: `ds_sales_ro`, `ds_hr_ro`; parolaları ayarlardan. Her biri yalnız kendi şemasında `USAGE` ve `SELECT` alır; `public` şemasındaki varsayılan yetkiler geri alınır.
- Seed: takımlar (`sales`, `hr`), üyelikler (design §5 tablosu), veri setleri (`db_role` ile), erişim izinleri. Upsert ile idempotent.
- `crypto.py`: `DAP_FERNET_KEY` ile şifrele / çöz (`teams.llm_key_enc` için).
- `bootstrap.py`: `python -m dap.db.bootstrap` sırayla migration, veri seti üretimi (doluysa atlar) ve seed'i çalıştırır. LiteLLM adımı Task 11'de eklenir.

**Kararlar:** K8, K9, K18

**Kabul ölçütleri:**
- `make lint test` → 0.
- `ds_sales_ro` ile bağlanınca: `sales.orders` okunur; `hr.salaries` "permission denied" verir; `sales`'e `INSERT` reddedilir.
- Üretici deterministiktir: iki ayrı üretimin tablo bazında satır sayıları ve içerik özeti aynıdır; sipariş sayısı 4.500–5.500 aralığındadır.
- `bootstrap` art arda iki kez çalışır; ikinci çalıştırma hata vermez, satır sayıları değişmez.

**Commit:** `feat(db): add synthetic datasets, read-only roles and seed`

- [x] Tamamlandı

### Task 3: SQL guard, sorgu yürütücü ve tool'lar

**Kilometre taşı:** M2

**Amaç:** K9'un uygulama katmanı ve ajanın dört tool'u (design §8).

**Dosyalar:** `backend/dap/agent/sql_guard.py`, `backend/dap/agent/executor.py`, `backend/dap/agent/tools.py`, `backend/tests/unit/test_sql_guard.py`, `backend/tests/unit/test_tools.py`, `backend/tests/integration/test_executor.py`

**İçerik:**
- `sql_guard.py`: `sqlglot` (postgres lehçesi) ile K9'daki kuralların tamamı. Ek kural (design §11): başka bir şemayla nitelenmiş tablo reddedilir. Reddetme, nedenini taşıyan tek bir istisna tipidir.
- `executor.py`: veri setinin kendi rolüyle bağlanır (ayrıcalıklı kullanıcı ve `SET ROLE` yok). Sorgu `BEGIN READ ONLY` içinde, `SET LOCAL statement_timeout = '5s'` ile, `search_path` veri seti şemasına ayarlı ve dış `LIMIT` sarmalıyla çalışır.
- `tools.py`: `list_tables`, `describe_table(table)` (şema bilgisi enjekte edilen önbellekte; Redis uygulaması dahil), `run_sql(sql)` (guard → yürütücü; modele en fazla 50 satır, uzun hücreler kırpılır), `final_answer(answer, sql)` (SQL yeniden çalışır, en fazla 200 satır; sonuç metin + SQL + kolonlar + satırlar; boş `sql` için design §8). Tool şemaları OpenAI function-calling biçimindedir. Guard reddi ve SQL hatası istisna olarak değil, modele dönen tool hatası olarak üretilir.
- I/O dışarıdan enjekte edilir (design §4, `agent` satırı); unit testler veritabanı kullanmaz.

**Kararlar:** K9, K21

**Kabul ölçütleri:**
- `make lint test` → 0.
- Guard unit testleri, izinli: düz `SELECT`, `JOIN`, salt-okuma CTE, alt sorgu, toplama. Yasaklı (her biri ayrı test durumu): `INSERT` / `UPDATE` / `DELETE`, `DROP` / `CREATE` / `ALTER`, çoklu ifade, `SELECT INTO`, veri değiştiren CTE, `set_config`, `pg_sleep`, K9 kara listesindeki her fonksiyon ailesinden bir örnek, şema dışı tablo.
- Yürütücü integration testleri: yazma denemesi `READ ONLY` nedeniyle veritabanında reddedilir (guard atlanarak); uzun süren sorgu `statement_timeout` ile kesilir; dış `LIMIT` uygulanır.

**Commit:** `feat(agent): add SQL guard, dataset executor and tools`

- [x] Tamamlandı

### Task 4: LLM sağlayıcıları ve ajan döngüsü

**Kilometre taşı:** M2

**Amaç:** Sağlayıcıdan bağımsız arayüz, iki adaptör (K2) ve döngü (design §8).

**Dosyalar:** `backend/dap/agent/llm.py`, `backend/dap/agent/providers/openai_compat.py`, `backend/dap/agent/providers/fake.py`, `backend/dap/agent/loop.py`, `backend/tests/unit/test_openai_compat.py`, `backend/tests/unit/test_loop.py`

**İçerik:**
- `llm.py`: `LLMProvider.complete(messages, tools, model, metadata) -> LLMResponse` (metin, tool çağrıları, token sayıları, varsa maliyet) ve hata tipleri (bütçe aşımı, sağlayıcıya ulaşılamadı).
- `OpenAICompatibleProvider`: `base_url` + anahtar; maliyet `x-litellm-response-cost` başlığından (`with_raw_response`); `metadata` isteğe eklenir. 429, 5xx ve zaman aşımında üstel beklemeyle 3 deneme (SDK'nın kendi yeniden denemesi kapalı, bekleme fonksiyonu enjekte edilebilir). Bütçe aşımı HTTP koduyla değil, hata gövdesindeki `budget_exceeded` tipiyle ayırt edilir (K4) ve yeniden denenmez.
- `FakeProvider`: senaryolu yanıtlar. Varsayılan senaryo herhangi bir veri setinde çalışır (`list_tables` → ilk tabloda `run_sql` → `final_answer`). Adımlar arasında `FAKE_STEP_DELAY_S` kadar bekler.
- `loop.py`: en fazla 8 adım. Her adımda olay üretir (`llm_call`, `tool_call`, `tool_result`, `answer`, `error`) ve bunları enjekte edilen bir geri çağrıya verir. Her adımın başında iptal kontrolü yapar. Sonuç: `succeeded`, `failed` (`step_limit`), `cancelled` ya da `budget_exceeded`; toplam token ve maliyet. Model tool çağırmadan yanıt verirse uyarı mesajıyla devam edilir ve bu da bir adım sayılır.

**Kararlar:** K2, K4, K17, K22

**Kabul ölçütleri:**
- `make lint test` → 0.
- Döngü (FakeProvider): tool → final başarıyla biter; 8 adımda final gelmezse `failed` / `step_limit`; iptal bayrağı bir sonraki adımın başında `cancelled` yapar; bütçe hatası `budget_exceeded` yapar; SQL hatası modele döner ve döngü devam eder.
- Adaptör (respx): tool çağrıları, token sayıları ve maliyet başlığı doğru okunur; 429'dan sonra 200 gelirse başarı; üç kez 500 gelirse ulaşılamadı hatası; `budget_exceeded` gövdesi bütçe hatasına çevrilir ve tek istek atılmıştır.

**Commit:** `feat(agent): add LLM providers and the agent loop`

- [x] Tamamlandı

### Task 5: API temeli: JWT, yetki ve takım uçları

**Kilometre taşı:** M3

**Amaç:** Kimlik doğrulama (design §7), yetki matrisi (design §6) ve koşu dışındaki uçlar.

**Dosyalar:** `backend/dap/authz.py`, `backend/dap/api/app.py`, `backend/dap/api/auth.py`, `backend/dap/api/deps.py`, `backend/dap/api/schemas.py`, `backend/dap/api/routes/health.py`, `backend/dap/api/routes/me.py`, `backend/dap/api/routes/teams.py`, `backend/tests/unit/test_authz.py`, `backend/tests/integration/test_api_auth.py`, `backend/tests/integration/test_api_teams.py`

**İçerik:**
- `authz.py`: saf `can(user, action, team, resource=None) -> bool`; yetkinin tek yeri.
- JWT: `OIDC_ISSUER` ve `OIDC_JWKS_URL` ayrı ayarlar; `aud` içinde `dap-api`; `email_verified=true`; `platform-admin` realm rolünden okunur. JWKS önbelleklenir, bilinmeyen `kid` gelince yenilenir.
- Uçlar (hepsi `/api` altında): `healthz`, `readyz` (Postgres, Redis, RabbitMQ), `me`, `teams/{team}/datasets`, `teams/{team}/members/{email}` (`PUT` / `DELETE`), `teams/{team}/datasets/{dataset}` (`PUT` / `DELETE`). Üye ve izin değişiklikleri `audit_log`'a yazılır.
- Üye olmayan kullanıcı ile var olmayan takım aynı 404'ü alır; yetersiz rol 403 alır.
- Testlerde JWKS sahtedir: test içinde üretilen RSA anahtarı.

**Kararlar:** K7, K8, K16

**Kabul ölçütleri:**
- `make lint test` → 0.
- Unit: design §6 matrisinin her hücresi (`resource` gerektirenler dahil) bir test durumudur.
- Integration: yanlış `aud`, `email_verified=false`, süresi dolmuş token ve yanlış `iss` ayrı ayrı 401 alır. alice `/api/me`'de `sales` / `analyst` görür. alice `hr` takımının veri setlerini isterse 404. bob üye eklemeye çalışırsa 403. carol `hr`'ye üye ekler: 200 ve `audit_log` satırı. Platform admin veri seti izni verir: 200 ve `audit_log` satırı. `readyz` servisler ayaktayken 200.

**Commit:** `feat(api): add JWT auth, authorization and team endpoints`

- [x] Tamamlandı

### Task 6: API koşuları: oluşturma, liste, iptal, SSE ve bütçe

**Kilometre taşı:** M3

**Amaç:** Koşu uçları, canlı olay akışı (K12) ve bütçe ön kontrolü (K4).

**Dosyalar:** `backend/dap/events.py`, `backend/dap/celery_app.py`, `backend/dap/litellm_client.py`, `backend/dap/api/routes/runs.py`, `backend/dap/api/routes/budget.py`, `backend/tests/integration/test_api_runs.py`, `backend/tests/integration/test_sse.py`

**İçerik:**
- `events.py` (API ve worker paylaşır): Redis kanal adı, iptal anahtarı adı, olayın JSON biçimi ve senkron olay yazıcı. Yazıcı önce Postgres'e yazar (`seq` koşu içinde artan), commit'ten sonra Redis'e yayınlar.
- `celery_app.py`: K10'daki ayarlarla Celery uygulaması ve task adı sabiti. Task'ın kendisi Task 7'dedir; API task'ı adıyla yayınlar.
- `POST /api/teams/{team}/runs`: yetki (izinsiz veri seti 403), kullanıcı başına dakikada 5 rate limit (Redis; aşımda 429), bütçe ön kontrolü, `queued` koşu satırı, kuyruğa yayın, `202 {run_id}`. Ön kontrol LiteLLM'den takım harcamasını okur ve Redis'te 60 sn önbellekler; limit dolmuşsa **402** ve `budget_exceeded` hata kodu döner, koşu oluşturulmaz. Takımın `litellm_team_id`'si yoksa ön kontrol atlanır.
- `GET` liste (cursor ile), `GET` detay (`attempts`, maliyet, `trace_id` dahil), `POST` iptal (Redis bayrağı), `GET /api/teams/{team}/budget` (LiteLLM harcama + limit, uygulamadan koşu bazında döküm).
- SSE (`GET /api/runs/{id}/events`): önce Redis'e abone olur, sonra kayıtlı olayları gönderir, sonra canlı olayları iletir; gönderilmiş `seq` atlanır. `Last-Event-ID` desteklenir. Koşu son durumuna ulaşınca akış kapanır.

**Kararlar:** K4, K10, K12

**Kabul ölçütleri:**
- `make lint test` → 0.
- alice `POST` → 202, koşu `queued`, RabbitMQ kuyruğunda bir mesaj. bob `POST` → 403. alice `hr` veri setiyle → 403. alice `hr` takımına → 404. Bir dakikada 6. `POST` → 429.
- Bütçe (LiteLLM respx ile sahte): limit dolmuşsa 402 ve koşu satırı yok; art arda iki istekte LiteLLM'e tek çağrı gider (önbellek).
- Liste sayfalaması bütün koşuları tekrarsız döndürür. analyst başkasının koşusunu iptal edemez (403), takım admin'i edebilir.
- SSE: bağlantıdan önce yazılan olaylar gelir; bağlantı sırasında yazılanlar gelir; abone olma ile replay arasında yarışan bir yazıcı varken olay kaybı ve tekrar yoktur; `Last-Event-ID` verilen `seq`'e kadar olanları atlar.

**Commit:** `feat(api): add run endpoints, SSE stream and budget checks`

- [x] Tamamlandı

### Task 7: Worker: advisory lock ile koşu sahipliği

**Kilometre taşı:** M4

**Amaç:** Koşuyu kuyruktan alıp ajan döngüsünü çalıştıran Celery task'ı (K10, K11, design §8 hata tablosu).

**Dosyalar:** `backend/dap/worker/lock.py`, `backend/dap/worker/runner.py`, `backend/dap/worker/tasks.py`, `backend/tests/integration/test_worker.py`, `backend/tests/integration/test_worker_lock.py`

**İçerik:**
- `lock.py`: `pg_try_advisory_lock`, anahtar koşu kimliğinden türetilir. Kilit `NullPool` + autocommit bir engine'den açılan ve koşu bitene kadar tutulan bağlantıdadır.
- `tasks.py`: K11'deki akış. Kilidi alamayan task koşuya dokunmaz, 30 sn sonra yeniden dener (en fazla 10); koşu bitmişse hiçbir şey yapmaz. Kilidi alan task koşu `queued` ya da `running` ise `attempts`'ı bir artırır ve baştan çalıştırır (ilk çalıştırmada `attempts=1`). `attempts` 3'ü geçerse koşu `failed` / `too_many_attempts` olur.
- `runner.py`: ayara göre sağlayıcıyı kurar (fake, ya da takımın şifresi çözülen anahtarıyla OpenAI uyumlu), tool'ları veri seti rolünün bağlantısıyla kurar, döngüyü çalıştırır. Olaylar `events.py` yazıcısıyla yeni `attempt` numarasıyla ve `seq` kaldığı yerden devam ederek yazılır. İptal Redis bayrağından okunur. Sonuçta durum, cevap, token, maliyet, model ve zaman damgaları kaydedilir. `SoftTimeLimitExceeded` → `failed` / `timeout`.

**Kararlar:** K9, K10, K11, K12, K21

**Kabul ölçütleri:**
- `make lint test` → 0.
- Uçtan uca (Celery test worker `solo` + FakeProvider): koşu `succeeded` olur; olaylar `seq` sırasıyla yazılmıştır; cevapta kolonlar ve satırlar vardır.
- Kilit başka bir bağlantıda tutulurken task koşuya dokunmaz ve retry planlar. Kilidi tutan bağlantı kapanınca task koşuyu alır ve `attempts` artar.
- `running` durumunda bırakılmış koşu (yarıda kalma benzetimi) `attempts=2` ile baştan çalışır; yeni olaylar `attempt=2` taşır ve `seq` devam eder.
- `attempts=3` olan koşu yeniden teslim edilince `failed` / `too_many_attempts`.
- İptal bayrağı → `cancelled`. Sahte bütçe hatası → `budget_exceeded`.
- Koşudan sonra havuz bağlantılarında advisory lock kalmamıştır (`pg_locks`).

**Commit:** `feat(worker): run agent tasks with advisory-lock ownership`

- [x] Tamamlandı

### Task 8: Langfuse izleme ve yapılandırılmış log

**Kilometre taşı:** M4

**Amaç:** Koşu başına trace (K5, K6) ve JSON log (design §9).

**Dosyalar:** `backend/dap/observability/tracing.py`, `backend/dap/observability/logging.py`, worker ve API'deki bağlama noktaları, `backend/tests/unit/test_tracing.py`, `backend/tests/unit/test_logging.py`

**İçerik:**
- Anahtar yoksa SDK hiç başlatılmaz; izleyici hiçbir şey yapmayan bir nesnedir (K5).
- Anahtar varsa: koşu başına bir trace, her tool çağrısı için bir span. Trace kimliği `runs.trace_id`'ye yazılır ve sağlayıcıya `metadata` ile geçilir. LiteLLM'e giden metadata anahtar adları tek bir yerde sabit olarak durur; doğru adlar Task 9'da doğrulanır.
- structlog ile JSON; worker'da her satır `run_id` ve `trace_id` taşır.

**Kararlar:** K5, K6

**Kabul ölçütleri:**
- `make lint test` → 0.
- Anahtarsız: Langfuse istemcisi hiç oluşturulmaz, koşu etkilenmez.
- Sahte istemciyle: bir trace, tool çağrısı sayısı kadar span, `trace_id` koşuya yazılmış.
- Worker log satırı geçerli JSON'dır ve `run_id` ile `trace_id` içerir.

**Commit:** `feat(observability): add Langfuse tracing and structured logs`

- [x] Tamamlandı

### Task 9: M5 doğrulama denemesi

**Kilometre taşı:** M5

**Amaç:** Chart'lar yazılmadan önce design'ın doğrulanmamış varsayımlarını denemek (design §13, M5). Ürün kodu yazılmaz.

**Dosyalar:** deneme dosyaları `runs/2026-11-19-m5-spike/` altında (git dışı, bir satırlık `README.md` ile); kalıcı çıktı bu dosyanın Karar günlüğü ve gerekirse `docs/design.md`.

**İçerik (her madde bir Karar günlüğü satırıdır; kaynak dokümanın sürümü yazılır):**
1. kind + Traefik (resmî chart, `NodePort` 30080): Git Bash'ten `curl` ile `PUBLIC_PORT`'a erişim ve `localtest.me` çözümlemesi. Kurulumda görülen: kind config'inde `failCgroupV1: false` yaması şart (Karar günlüğü).
2. Keycloak: sabitlenecek image sürümü; realm import'ta kullanıcı parolası için `${ENV}` yer tutucusu çalışıyor mu (çalışmıyorsa parolalar bootstrap'ta admin API ile atanır, design §5); `KC_HOSTNAME` ile `iss`; audience mapper ile `aud=dap-api`.
3. LiteLLM: image digest'i; `claude-haiku-5-5` ve `claude-sonnet-5-5` adlarının geçerliliği (model başına tek, birkaç token'lık gerçek çağrı); açık `model_info` fiyatlarıyla `x-litellm-response-cost` başlığının sıfırdan büyük gelmesi; takım, anahtar ve harcama uçlarının istek / yanıt biçimi; bütçe aşımı hatasının gerçek biçimi (çok küçük bütçeli deneme takımıyla). Fiyatların kaynağı (Anthropic'in resmî fiyat sayfası) ve tarihi yazılır.
4. Langfuse: kurulan LiteLLM sürümünde trace kimliğini taşıyan metadata anahtar adları (dokümandan; Langfuse anahtarı varsa canlı).
5. Helm 4.3.2 ile `pre-install` / `pre-upgrade` hook'ları ve `--wait` davranışı (küçük bir deneme chart'ıyla).

**Kararlar:** K3, K4, K6, K7, K14, K17

**Kabul ölçütleri:**
- Karar günlüğünde 1–5 için birer satır var; her satır `runs/2026-11-19-m5-spike/` altındaki kanıt dosyasına atıf yapıyor.
- Yanlış çıkan her varsayım için `docs/design.md`'deki ilgili satır aynı commit'te düzeltilmiş.
- Deneme cluster'ı silinmiş: `kind get clusters` boş.
- O ana kadarki API harcaması Sabah raporuna yazılmış.
- `ANTHROPIC_API_KEY` boşsa 3. maddenin gerçek çağrıları yapılmaz ve bu Engeller'e yazılır; geri kalan maddeler tamamlanır.

**Commit:** `docs: record M5 validation spike results`

- [x] Tamamlandı

### Task 10: Backend image'ı, kind config'i ve infra chart'ı

**Kilometre taşı:** M5

**Amaç:** Cluster'ın altyapı yarısı: `make up` 1–4. adımları (design §10).

**Dosyalar:** `backend/Dockerfile`, `.dockerignore`, `deploy/kind/kind-config.yaml`, `deploy/values/traefik.yaml`, `deploy/charts/infra/`, `deploy/keycloak/realm-export.json`, `scripts/secrets.sh`, `Makefile` (`up`, `down`, `helm-lint`)

**İçerik:**
- Backend image'ı: çok aşamalı, uv ile, root olmayan kullanıcı; api, worker ve bootstrap aynı image'ı kullanır.
- kind config'i: tek node, `containerPort: 30080` → host `PUBLIC_PORT`, kubelet için `failCgroupV1: false` yaması.
- `infra` chart'ı (resmî image'lar, K15): Postgres StatefulSet + PVC (`dap`, `datasets`, `litellm` veritabanları), Redis, RabbitMQ, Keycloak (realm import, `KC_HOSTNAME` dış adres, `auth.localtest.me` Ingress'i), LiteLLM (digest ile sabit, `default` ve `strong` takma adları, açık `model_info` fiyatları, `startupProbe`, Langfuse callback'i yalnız anahtar varsa). Her iş yükünde `requests` / `limits`, probe'lar ve `securityContext`.
- Realm: `dap-web` (public, PKCE) ve `dap-smoke` (direct grant açık) client'ları, `aud=dap-api` mapper'ı, sabit `id`'li ve e-postası doğrulanmış dört kullanıcı. Parolalar Task 9'un 2. maddesinin sonucuna göre verilir; repoya girmez.
- `scripts/secrets.sh`: Secret'ları `.env`'den üretir; `CI=true` ise eksikler için rastgele değer üretir; değerleri yazdırmaz.
- Bütün dış adresler tek `publicPort` değerinden türer (K16).
- `make helm-lint`: `helm lint` + `helm template | kubeconform`.

**Kararlar:** K3, K5, K7, K14, K15, K16, K17, K21

**Kabul ölçütleri:**
- `make helm-lint` → 0.
- `make down; make up` sonrası `kubectl get pods -A`: bütün infra pod'ları `Ready`.
- `curl http://auth.localtest.me/realms/dap/.well-known/openid-configuration` → `issuer` dış adrestir.
- `dap-smoke` ile alice için alınan token'da `aud` `dap-api` içerir, `email_verified` true'dur, `iss` dış adrestir (token ekrana yazdırılmaz, yalnız bu alanlar).
- `docker stats --no-stream` çıktısı Karar günlüğüne yazılmış.

**Commit:** `feat(deploy): add backend image, kind config and infra chart`

- [x] Tamamlandı

### Task 11: Platform chart'ı, bootstrap Job'ı ve smoke

**Kilometre taşı:** M5

**Amaç:** Uygulamanın cluster'da uçtan uca çalışması: `make up && make smoke` (design §10, §11 E2E).

**Dosyalar:** `deploy/charts/platform/`, `backend/dap/db/bootstrap.py` (LiteLLM adımı), `backend/dap/litellm_client.py` (takım ve anahtar oluşturma), `scripts/smoke.sh`, `Makefile` (`up` tamamı, `smoke`)

**İçerik:**
- `platform` chart'ı: api ve worker Deployment'ları, bootstrap Job'ı (`pre-install` / `pre-upgrade` hook; ConfigMap ve ServiceAccount'ı daha düşük `hook-weight` ile), `app.localtest.me` altında `/api` yönlendirmesi. `/api/metrics` dışarı açılmaz.
- Worker: prefork havuzu, design §10'daki liveness probe'u, readiness yok.
- Bootstrap'ın LiteLLM adımı: her takım için LiteLLM takımı (`max_budget` values'tan, varsayılan takım başına 1 USD) ve sanal anahtar; `litellm_team_id` ve şifreli anahtar `teams`'e yazılır. İdempotent.
- `llm.provider: fake` varsayılan (K22). `make up REAL_LLM=1` worker'ı LiteLLM'e bağlar.
- `scripts/smoke.sh` (her zaman fake): design §11 E2E satırındaki senaryoların tamamı, worker ölümü dahil (`FAKE_STEP_DELAY_S` ile uzatılan koşu, `kubectl delete pod --grace-period=0 --force`, sonuç `attempts=2` ve `succeeded`). Her kontrolü adıyla yazdırır; biri başarısızsa sıfırdan farklı kodla çıkar. `--resolve` yedeği vardır.

**Kararlar:** K4, K10, K11, K16, K22

**Kabul ölçütleri:**
- `make helm-lint` → 0.
- `make up && make smoke` → 0; çıktıda her senaryo "ok".
- `make up` ikinci kez çalışır (bootstrap Job yeniden koşar, hata yok, takım anahtarları çoğalmaz).
- **Elle gerçek koşu (orkestratör yapar):** `make up REAL_LLM=1`, alice'in token'ıyla tek koşu → `succeeded`; koşu detayında `cost_usd > 0` ve LiteLLM takım harcamasında aynı koşu görünür. Sonra `make up` ile fake'e dönülür. Harcama Sabah raporuna yazılır. `ANTHROPIC_API_KEY` boşsa bu madde yapılmaz ve Engeller'e yazılır.

**Commit:** `feat(deploy): add platform chart, bootstrap job and smoke test`

- [x] Tamamlandı

### Task 12: Metrikler, Prometheus ve Grafana

**Kilometre taşı:** M6

**Amaç:** design §9'daki metrikler ve tek dashboard.

**Dosyalar:** `backend/dap/observability/metrics.py`, api ve worker'daki bağlama noktaları, `deploy/values/prometheus.yaml`, `deploy/values/grafana.yaml`, dashboard ConfigMap şablonu, chart'lardaki kazıma annotation'ları, `Makefile` (`up` 6. adım), `backend/tests/unit/test_metrics.py`

**İçerik:**
- Metrik adları design §9'dakilerle birebir aynıdır. Worker `:9200`'de, `prometheus_client` multiprocess modunda (`PROMETHEUS_MULTIPROC_DIR`, `emptyDir`).
- `prometheus-community/prometheus` chart'ı yalnız server ile (alertmanager, pushgateway, node-exporter, kube-state-metrics kapalı); pod annotation'larıyla kazıma.
- Grafana resmî chart'ı, `grafana.localtest.me`; dashboard ConfigMap ile provision edilir. Paneller: koşu hızı ve durum dağılımı, p95 koşu süresi, takım bazında maliyet, tool hata oranı, API p95.

**Kararlar:** K15, K16

**Kabul ölçütleri:**
- `make lint test` → 0; `make helm-lint` → 0.
- `make up && make smoke` sonrası Prometheus'a `curl` ile sorgu: `dap_runs_finished_total` ve `dap_runs_created_total` boş olmayan sonuç döner; API istek süresi histogramı da kazınmıştır.
- Dashboard ConfigMap'i cluster'dadır ve Grafana API'si dashboard'u listeler.
- `curl http://app.localtest.me/api/metrics` → 404.
- `docker stats --no-stream` toplamı Karar günlüğüne yazılmış (hedef 4 GB altı; aşılırsa `requests` / `limits` ayarlanır).

**Commit:** `feat(observability): add metrics, Prometheus and Grafana dashboard`

- [x] Tamamlandı

### Task 13: Frontend uygulaması

**Kilometre taşı:** M7

**Amaç:** React arayüzü (design §2 demo senaryosu, K13, K16).

**Dosyalar:** `frontend/` (Vite + React + TypeScript), `Makefile` (`frontend-check`)

**İçerik:**
- TypeScript strict; yönlendirme için `react-router`; giriş `oidc-client-ts` ile PKCE; SSE `@microsoft/fetch-event-source` ile. Başka UI ya da state kütüphanesi yok, düz CSS. Metinler İngilizce.
- Ayarlar build'e gömülmez: `/config.js` içindeki `window.__CONFIG__`'ten okunur (API adresi, OIDC issuer, client id, varsa Langfuse adresi).
- Dört sayfa: koşu listesi (takım seçimi, sayfalama); yeni koşu (yalnız izinli veri setleri); koşu detayı (denemeye göre gruplanmış canlı zaman çizelgesi, cevap tablosu, SQL, maliyet, varsa Langfuse linki, iptal); takım yönetimi (üyeler, bütçe). Role göre gizlenen kontroller API'deki yetkiyle uyumludur (viewer yeni koşu başlatamaz).
- `make frontend-check`: eslint, `tsc --noEmit`, vitest, build.

**Kararlar:** K12, K13, K16, K19

**Kabul ölçütleri:**
- `make frontend-check` → 0.
- vitest: zaman çizelgesi indirgeyicisi tekrarlanan `seq`'i atar ve olayları `attempt`'e göre gruplar; viewer için "new run" kontrolü görünmez; API istemcisi `Authorization` başlığını ekler.

**Commit:** `feat(frontend): add React app with OIDC login and live run view`

- [x] Tamamlandı

### Task 14: Frontend image'ı ve chart'a eklenmesi

**Kilometre taşı:** M7

**Amaç:** Arayüzün cluster'dan sunulması.

**Dosyalar:** `frontend/Dockerfile`, `frontend/nginx.conf`, `config.js` üreten giriş script'i, `deploy/charts/platform/templates/` (frontend Deployment, Service, yönlendirme), `Makefile` (`up`), `scripts/smoke.sh`

**İçerik:**
- Root olmayan nginx image'ı statik dosyaları sunar. Container açılırken ortam değişkenlerinden `config.js` üretilir (K16); salt-okunur kök dosya sistemiyle çalışır.
- `app.localtest.me`'de `/` frontend'e, `/api` API'ye gider.
- `make up` frontend image'ını da build edip `kind load` ile yükler. smoke'a ana sayfa ve `config.js` kontrolü eklenir.

**Kararlar:** K7, K16

**Kabul ölçütleri:**
- `make helm-lint` → 0.
- `make up && make smoke` → 0.
- `curl -s -o /dev/null -w '%{http_code}' http://app.localtest.me/` → 200.
- `curl http://app.localtest.me/config.js` çıktısında issuer geçerli `PUBLIC_PORT`'u taşır ve client id `dap-web`'dir.
- `curl http://app.localtest.me/api/healthz` → 200.

**Commit:** `feat(deploy): serve the frontend from the platform chart`

- [x] Tamamlandı

### Task 15: CI workflow ve README

**Kilometre taşı:** M8

**Amaç:** GitHub Actions (design §12) ve README'nin gece sonu hali.

**Dosyalar:** `.github/workflows/ci.yml`, `Makefile` (`ci`), gerekirse `deploy/values/ci.yaml`, `README.md`

**İçerik:**
- Dört iş: `python` (`make lint test`), `frontend` (`make frontend-check`), `helm` (`make helm-lint`), `e2e-kind` (ilk üçünden sonra; `CI=true make up` ve `make smoke`). Kurulum action'ları sürümle sabitlenir; Helm ana sürümü yereldekiyle aynıdır (4).
- `make ci` = `lint test frontend-check helm-lint`.
- README: hızlı başlangıç, `make` hedefleri, adresler, seed kullanıcıları (parolalar `.env`'den), mimari, tasarım kararlarının özeti, bilinen sınırlar, "Production gaps". Karşılığı `runs/` ya da `eval/results/` altında olmayan ölçüm sayısı yazılmaz (K23). AI bölümü yok (K20).

**Kararlar:** K19, K20, K22, K23

**Kabul ölçütleri:**
- `make ci` → 0.
- `ci.yml` geçerli YAML'dır ve kurulum dışındaki her `run:` adımı yalnız `make` çağırır.
- `make down; make up && make smoke` → 0 (temiz cluster'da).

**Commit:** `ci: add GitHub Actions workflow and finish the README draft`

- [x] Tamamlandı

## Karar günlüğü

| Zaman | Görev | Karar | Gerekçe |
|---|---|---|---|
| 2026-11-19 00:52 | Kurulum | Repo `~/data-agent-platform` yerine `C:\Users\Yusuf Altuntaş\Desktop\data-agent-platform`'a klonlandı. design §13 ve bu dosyanın "Ortam" bölümü buna göre düzeltildi. | Oturum bu boş klasörde açıldı; dosya izinleri ve dosya paneli çalışma klasörünü kapsıyor. Masaüstü OneDrive'a bağlı değil (`[Environment]::GetFolderPath('Desktop')` yerel yolu döndürüyor). |
| 2026-11-19 00:56 | Kurulum | winget ile kuruldu: GitHub CLI 2.105.0, kind 0.33.0, Helm 4.3.2, kubeconform 0.8.0, GNU make 4.4.1 (`ezwinports.make`), jq 1.8.2, kubectl 1.37.2. Zaten vardı: Docker Desktop (engine 27.5.1), uv 0.13.9, Node.js 24.15.0. | design §13 araç listesi. jq listede yoktu ama `scripts/smoke.sh` kullanıyor (design §11); listeye eklendi. `GnuWin32.Make` 3.81'de kaldığı için `ezwinports.make` seçildi. |
| 2026-11-19 01:00 | Kurulum | Güncel `kubectl.exe` (1.37.2) `~/bin`'e kopyalandı. | Docker Desktop kendi kubectl 1.31.4'ünü sistem PATH'ine koyuyor ve winget'inkinin önüne geçiyor; kind'ın node'u 1.37 olduğu için fark desteklenen ±1 sınırını aşıyordu. Git Bash `~/bin`'i PATH'in başına koyar. PowerShell'den çağrılan `kubectl` hâlâ 1.31.4'tür; `make` Git Bash'ten çalıştırılır. |
| 2026-11-19 01:03 | Kurulum | kind config'inde kubelet için `failCgroupV1: false` yaması kullanılacak (Task 10). | Docker Desktop bu makinede cgroup v1 kullanıyor (`docker info`: `Cgroup Version: 1`, WSL çekirdeği 5.15). Kubernetes 1.37 kubelet'i cgroup v1'de varsayılan olarak başlamıyor: yamasız `kind create cluster` kubeadm'de düştü, yamayla kuruldu. CI'da (cgroup v2) yama etkisizdir. Kalıcı çözüm Docker Desktop / WSL güncellemesidir; gece öncesi riskli bulunduğu için yapılmadı. |
| 2026-11-19 01:05 | Kurulum | Ön deneme: kind + `NodePort` 30080 → host 80 çalışıyor; `curl http://app.localtest.me/` 200 döndü, `localtest.me` 127.0.0.1'e çözülüyor. 80 portu boş, `publicPort` 80 kalır. Docker'ın gördüğü bellek 7,6 GiB (sınır 6). Tek node'lu boş cluster 732 MiB. | Gece karşılaşılacak ortam engellerini kullanıcı başındayken yakalamak için. Task 9'un 1. maddesi Traefik'le birlikte yeniden doğrular. |
| 2026-11-19 01:05 | Kurulum | `docker login` yapılmadı. | İsteğe bağlı (design §13). Risk: Docker Hub'ın anonim çekme sınırı (IP başına 6 saatte 100). Gece çekilecek image sayısı bunun altında bekleniyor; sınıra takılınırsa Engeller'e yazılır. |
| 2026-11-19 01:12 | Plan | SQL guard, başka bir şemayla nitelenmiş tabloyu da reddeder (Task 3). design K9 buna göre güncellendi. | design §11 unit testleri "şema dışı tablo"yu guard kapsamında sayıyor, K9'un kural listesinde yoktu. Asıl engel yine veritabanı rolüdür; bu kural modele daha anlaşılır bir hata döndürür. |
| 2026-11-19 01:12 | Plan | Bütçe ön kontrolü aşımda HTTP 402 ve `budget_exceeded` hata kodu döner (Task 6). design §7'ye yazıldı. | design durum kodunu belirtmiyordu. 403 yetkiyle, 429 rate limit'le karışırdı. |
| 2026-11-19 01:14 | Plan | Takım başına LiteLLM bütçesi 1 USD (Task 11, values'tan değiştirilebilir). | design tutar vermiyordu. Kullanıcının Anthropic bakiyesi toplam 5 USD ve artırılamıyor. İki takım × 1 USD = gece için en fazla 2 USD'lik sert üst sınır; kalan bakiye ertesi günkü eval'e (M9) kalır. |
| 2026-11-19 01:12 | Plan | `runs.attempts` 0'dan başlar ve task koşuyu her sahiplendiğinde bir artar; ilk çalıştırma `attempts=1`'dir (Task 7). | design §11 smoke'u tek bir worker ölümünden sonra `attempts=2` bekliyor; K11 yalnız yeniden başlamadaki artışı anlatıyordu. |
| 2026-11-19 01:12 | Plan | Python 3.13. Ajan kütüphanesi senkron yazılır. | design sürüm vermiyordu. Ajanı yalnız senkron worker çalıştırır (K21); async bir ikinci yol gereksiz. |
| 2026-11-19 01:18 | Task 0 | `backend/.venv` yorumlayıcının tam yoluyla kuruldu: `cd backend && uv venv --python "$APPDATA/uv/python/cpython-3.13.18-windows-x86_64-none/python.exe" && uv sync`. `.venv` silinirse ya da repo yeniden klonlanırsa aynı komut gerekir. Alt agent hata ayıklarken uv'nin kullanıcı dizinindeki Python 3.13 kısayol klasörünü silip yeniden oluşturdu (repo dışı). | uv 0.13.9, kullanıcı yolundaki "ş" yüzünden kendi indirdiği Python 3.13'ün kısayolunu çözemiyor. Kalıcı çözüm `UV_PYTHON_INSTALL_DIR`'ı ASCII bir klasöre almak; kullanıcı ortam değişkeni olduğu için gece yapılmadı. Yalnız bu makineyi etkiler; CI'ı ve container'ları etkilemez. |
| 2026-11-19 01:30 | Task 1 | **Ruling:** `Settings` `.env` dosyasını yüklemez, yalnız süreç ortamını okur. Reviewer bunu "Important" bulgu olarak işaretledi; düzeltme yapılmadı, "Ortak kurallar"daki cümle netleştirildi. | Bulgu, ortak kurallardaki "`.env` okunur" ifadesinin belirsizliğinden doğdu; kastedilen alt agent'ların dosyayı ele alışıydı. Cluster'da değerler Secret'tan ortam değişkeni olarak gelir, testler ayarı fixture'la verir. Uygulamanın `.env`'i kendisi yüklemesi testlere gerçek parolaları sızdırırdı. Host'tan elle komut çalıştırmak gerekirse değişkenler dışarıdan verilir. |
| 2026-11-19 01:30 | Task 1 | Veritabanı bağlantısı tek bir URL yerine ayrı ayarlardan kurulur: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DAP_DB_NAME`. `run_events.type` için check kısıtı yok. | Uygulayıcının varsayımı. Aynı sunucuda üç veritabanı olduğu için (design §10) parçalı ayar chart'ta daha az tekrar demek. Plan yalnız `role` ve `runs.status` için check istiyordu. |
| 2026-11-19 01:46 | Task 2 | `backend/tests/conftest.py`'ye testcontainers'ın Ryuk container'ı için küçük bir yeniden deneme eklendi. Sorun sürerse yedek: `TESTCONTAINERS_RYUK_DISABLED=true`. | testcontainers 4.15, Docker Desktop'ta Ryuk'u ara sıra başlatamıyor ve testler rastgele düşüyordu. Plandaki dosya listesinin dışında bir değişiklik; reviewer "Minor" olarak not etti. |
| 2026-11-19 01:46 | Task 2 | Seed, üyelik ve izinleri "yoksa ekle" ile yazar (takımlarda yalnız `name` güncellenir). Admin'in API'den değiştirdiği rol korunur; admin'in sildiği seed üyeliği bir sonraki `helm upgrade`'de geri gelir. | Uygulayıcının tercihi: bootstrap her yükseltmede koştuğu için admin değişikliklerini ezmemeli. Silinenin geri gelmesi demo verisi için kabul edilebilir. |
| 2026-11-19 01:46 | Task 2 | `ds_*_ro` rolleri `dap` ve `litellm` veritabanlarına bağlanabiliyor (tablo okuyamaz, adlarını görebilir). Bu bağlantı yetkisi Task 10'da Postgres kurulumunda kapatılacak. | Postgres varsayılan olarak her role her veritabanına bağlanma izni verir. `datasets` veritabanında PUBLIC'in yetkileri zaten geri alındı. |
| 2026-11-19 02:03 | Task 3 | Sorgu yürütücü kullanıcı sorgusunu Postgres'in genişletilmiş protokolüyle gönderir (`binary=True`); tek metinde birden çok ifade veritabanında reddedilir (`393530a`). | Review bulgusu: basit protokolde, guard'ı aşan `...; COMMIT; ...` biçimli bir sorgu `READ ONLY` işlemini ve zaman aşımını da devre dışı bırakabiliyordu (yeni test düzeltmeden önce kırmızıydı). K9'un ikinci katmandan bağımsız çalışması gerekir. Yan etki: `money`, `xml`, `tsvector` gibi nadir tipler ham bayt olarak döner (final review listesinde). |
| 2026-11-19 02:03 | Task 3 | Bilinen sınır: `query_to_xml` gibi metinden SQL çalıştıran fonksiyonlar K9 kara listesinde yok; guard'dan geçer. Salt-okuma rolü ve `READ ONLY` işlem yine de sınırlar. README'nin bilinen sınırlar bölümüne yazılacak (Task 15). | Kara liste design K9'daki listeyle birebir uygulandı; liste genişletilmedi. |
| 2026-11-19 02:13 | Task 4 | `openai` kütüphanesi `>=2,<3` aralığına sabitlendi (kurulan 2.54.0). | 3.55.1 HTTP katmanı olarak `httpx2` kullanıyor; planın istediği respx yalnız `httpx`'i yakalayabildiği için adaptör testleri yazılamıyordu. respx `httpx2` desteği kazanırsa sabitleme kaldırılabilir. |
| 2026-11-19 02:13 | Task 4 | Yeniden denenemeyen sağlayıcı hataları (örn. 401) koşuyu `failed` / `llm_error`, üç denemede ulaşılamayan sağlayıcı `failed` / `llm_unavailable` yapar. Yeni ayarlar: `LLM_PROVIDER` (`fake` / `openai_compatible`), `LLM_BASE_URL`, `LLM_MODEL` (varsayılan `default`), `FAKE_STEP_DELAY_S`. | design §8 hata tablosu bu iki durum için hata kodu vermiyordu. |
| 2026-11-19 02:30 | Task 5 | Host test koşularında testcontainers'ın Ryuk container'ı kapatıldı (`tests/conftest.py`); Task 2'deki yeniden deneme kaldırıldı. Tam test takımı art arda 3 kez geçti. | Yeniden deneme yetmedi: Task 4'te bir tam koşu Ryuk yüzünden düştü. Oturum kapsamlı fixture'lar container'larını zaten kendileri durduruyor. Bedeli: test koşusu yarıda öldürülürse test container'ları açık kalabilir. |
| 2026-11-19 02:30 | Task 5 | RabbitMQ kullanıcısı varsayılan `dap`; `RABBITMQ_PASSWORD` bootstrap dahil her süreç için zorunlu ayar. JWT yalnız RS256 kabul eder; JWKS yenilemesi 10 sn'de bire sınırlı. | Uygulayıcının varsayımları. Uydurma `kid`'lerle Keycloak'a istek yağdırılmasını önler. Chart'ın bu kullanıcıyı oluşturması ve `OIDC_JWKS_URL`'i cluster içi adrese ayarlaması Task 10–11'e not edildi. |
| 2026-11-19 02:57 | Task 6 | Kuyruğa yayın başarısız olursa koşu `failed` / `enqueue_failed` olur ve API 503 döner. Bütçe ön kontrolünde LiteLLM'e ulaşılamazsa API 503 döner (kontrol atlanmaz). `LITELLM_MASTER_KEY` her süreç için zorunlu ayar. Bütçe ucu son 100 koşuyu döker. Canlı akışta atlanan bir `seq` görülürse olaylar veritabanından yeniden okunur. | design bu durumları belirtmiyordu. İlk ikisi review bulgusu ve uygulayıcının tercihi: `queued`'da asılı kalan koşu yerine dürüst bir hata; bütçe okunamıyorken koşu başlatmamak. Bedeli: `/team/info` erişilemezken LiteLLM'e bağlı takımlar koşu başlatamaz. |
| 2026-11-19 02:57 | Task 9 | **1. kind + Traefik: varsayım tuttu.** Traefik chart 42.4.1 (v3.7.19), `NodePort` 30080; Git Bash'ten `curl http://app.localtest.me/` 200. Values anahtarı `service.spec.type: NodePort` olmalı (`service.type` şema hatası verir). `localtest.me` 127.0.0.1 ve ::1'e çözülüyor; eşleme yalnız IPv4'te, `curl` IPv4'e düşüyor. | Kanıt: `runs/2026-11-19-m5-spike/1-traefik/`. Kaynak: `https://traefik.github.io/charts`, chart 42.4.1. |
| 2026-11-19 02:57 | Task 9 | **2. Keycloak: varsayım tuttu.** Image `quay.io/keycloak/keycloak:26.8.2`. Realm import'ta parola için `${DEGISKEN}` çalışıyor, `${env.DEGISKEN}` çalışmıyor; admin API yedeğine gerek kalmadı (design §5 düzeltildi). `KC_HOSTNAME` ile host'tan ve cluster içinden alınan token'ların `iss`'i aynı. Audience mapper `aud="dap-api"` veriyor (liste değil, metin). Rolü olmayan kullanıcıda `realm_access` claim'i hiç yok; API kodu ikisini de doğru işliyor (`auth.py`). Probe'lar 9000 portunda. Bellek 639 MiB (tepe 825). | Kanıt: `runs/2026-11-19-m5-spike/2-keycloak/`. Keycloak 26.8.2. |
| 2026-11-19 02:57 | Task 9 | **3. LiteLLM: varsayım tuttu.** Image `ghcr.io/berriai/litellm-database:v1.110.0` (digest FINDINGS'te). `claude-haiku-5-5` ve `claude-sonnet-5-5` gerçek çağrıyla geçerli; `x-litellm-response-cost` sıfırdan büyük ve açık fiyatlarla birebir uyuşuyor. Fiyatlar: haiku 0,10 / 0,50 USD, sonnet 2 / 10 USD (girdi / çıktı, milyon token başına). `GET /team/info` doğru uç: `.team_info.spend`, `.team_info.max_budget`. Bütçe aşımı HTTP 422, `error.type = "budget_exceeded"`; limit bir istek gecikmeli uygulanıyor (design K4'e yazıldı). Bellek 708 MiB (tepe 776). | Kanıt: `runs/2026-11-19-m5-spike/3-litellm/`. Fiyat kaynağı: `https://platform.claude.com/docs/en/about-claude/pricing`, 2026-11-19'da okundu. |
| 2026-11-19 02:57 | Task 9 | **4. Langfuse: K6 düzeltildi.** LiteLLM 1.110.0'a `trace_id` değil `existing_trace_id` (32 hex) ve `parent_observation_id` (16 hex) gönderilmeli. Callback Langfuse SDK `>=4.7,<5` istiyor. K6'daki "generation'ı uygulama yazar" yedeğine gerek görülmedi. **Canlı sınanmadı** (Langfuse anahtarı yok). | Kanıt: `runs/2026-11-19-m5-spike/4-langfuse/`. Kaynak: LiteLLM 1.110.0 kaynak kodu ve `https://docs.litellm.ai/docs/proxy/logging`. |
| 2026-11-19 02:57 | Task 9 | **5. Helm 4.3.2 hook'ları: varsayım tuttu.** Hook ConfigMap ve ServiceAccount (ağırlık -10) Job'dan önce oluşuyor; Helm hook Job'ını `--wait` olmadan da bekliyor; Job başarısızsa yeni sürüm `failed`, eski pod'lar çalışmaya devam ediyor. Silme politikası `before-hook-creation` olmalı. `--atomic` yerine `--rollback-on-failure`. | Kanıt: `runs/2026-11-19-m5-spike/5-helm-hooks/`. |
| 2026-11-19 02:57 | Task 9 | Bellek: yalnız Traefik, Keycloak, LiteLLM ve bir Postgres ile kind node'u 3,04 GiB'a çıktı. 4 GB cluster hedefi (design §10) dar; Task 10–12'de ölçülecek. | Kanıt: `runs/2026-11-19-m5-spike/memory.txt`. |
| 2026-11-19 02:57 | Task 9 | `.env`'de `ANTHROPIC_API_KEY=ANTHROPIC_API_KEY=sk-ant-…` biçiminde yapıştırılmış satırdaki fazladan önek silindi. Anahtarın değeri değiştirilmedi ve hiçbir yere yazdırılmadı. | Değişken adı iki kez yapıştırılmıştı; denemenin ilk iki gerçek çağrısı bu yüzden 401 aldı (ücretsiz). Düzeltilmeseydi `scripts/secrets.sh` bozuk değeri cluster'a taşır ve gece gerçek model doğrulaması yapılamazdı. |
| 2026-11-19 02:57 | Task 9 | Task 9 için ayrı bir reviewer alt agent'ı açılmadı. | Görev ürün kodu üretmiyor; bulgular Task 10–11'in kabul ölçütleriyle (gerçek cluster) sınanıyor. Abonelik kotasını korumak için. |
| 2026-11-19 03:00 | Task 13 | **Ruling:** Task 13 (frontend), Task 7 ile aynı anda ayrı bir git worktree'de (`.claude/worktrees/task-13`, dal `task-13-frontend`) uygulandı; commit'leri sonra `main`'e alındı. Bu, "Orkestrasyon"daki "worktree açılmaz" ve "Paralellik"teki "repoya aynı anda tek uygulayıcı yazar" kurallarından bilinçli bir sapmadır. | Süre kazanmak için. Worktree yasağının gerekçesi (`.env`, `deploy/secrets/`, cluster durumu) bu görev için geçerli değil: yalnız `frontend/` ve Makefile'da tek hedef değişiyor, test için Docker ve cluster gerekmiyor. İki uygulayıcı aynı dosyaya dokunmadı. |
| 2026-11-19 03:10 | Kayıt | Bu günlükteki 01:18–02:57 arası zamanlar commit zamanlarına göre düzeltildi. | Orkestratör zamanları tahminle yazmıştı ve bazıları gerçeğin bir saate kadar ilerisindeydi. Bundan sonra saat sistemden okunuyor. |
| 2026-11-19 03:28 | Task 7 | Koşunun durumu hiç kaydedilemiyorsa (Postgres ya da Redis erişilemez) task mesajı onaylatmaz, 30 sn arayla en fazla 10 kez yeniden dener (`2c6901e`). **Bilinen sınır:** bağımlılık 10 denemenin hepsinde kapalı kalırsa mesaj onaylanır ve koşu `running` / `queued` durumunda kalabilir. Worker'ın yazdığı ek hata kodları: `timeout`, `internal_error`, `too_many_attempts`. `timeout` ve `internal_error` ile biten koşuda o ana kadarki token ve maliyet kaydedilmez. | Review bulgusu: koruma yalnız ajan döngüsünü sarıyordu; kısa bir Redis kesintisi koşuyu sonsuza kadar askıda bırakabiliyordu. design §8 hata tablosu altyapı kesintisini kapsamıyor. Sınırsız yeniden deneme yerine sınırlı deneme seçildi. |
| 2026-11-19 03:28 | Task 13 | Task 13'ün alt agent'ı `vite preview` sunucusunu (port 4173) açık bırakmıştı; süreç durduruldu, worktree klasörü ve `task-13-frontend` dalı silindi (içerik `main`'dekiyle aynıydı). | Süreç worktree klasörünü kilitli tutuyordu. Projenin kendi oluşturduğu süreç ve klasör. |
| 2026-11-19 04:00 | Task 8 | Task 8 de Task 10 ile paralel, ayrı bir worktree'de (`task-8-observability`) uygulandı ve `main`'e alındı. İki görev de `backend/pyproject.toml`'a bağımlılık eklediği için çakışmayı orkestratör çözdü (iki satır da korundu, `uv lock` yeniden üretildi; `make lint test` → 243 passed). Worktree ve dal silindi. | Task 13'teki Ruling'in aynısı: süre. Çakışma yalnız bağımlılık listesindeydi. |
| 2026-11-19 04:00 | Task 8 | Trace kimliği koşu kimliğinin hex hali; yalnız izleme açıkken `runs.trace_id`'ye yazılır. Her koşunun sonunda Langfuse'a flush yapılır: Langfuse erişilemezse worker o koşunun yuvasını yaklaşık 30 sn tutabilir (koşunun sonucu etkilenmez). Celery'nin kendi "received / succeeded" satırları `run_id` alanı taşımaz. | K6'nın uygulanışı ve bilinen sınırları. Worker süreci koşudan sonra öldürülebileceği için flush koşu sonunda yapılıyor. Celery'nin satırları task kodunun dışında yazılıyor. |
| 2026-11-19 04:01 | Task 10 | Bellek (`docker stats --no-stream`): yalnız altyapı (Postgres, Redis, RabbitMQ, Keycloak, LiteLLM, Traefik) kuruluyken `dap-control-plane 3.054GiB / 7.614GiB`. `requests` toplamı düşük tutuldu; api, worker, Prometheus ve Grafana eklenince 4 GB hedefi aşılabilir. | design §10'un ölçüm şartı. Task 11 ve Task 12'de yeniden ölçülecek. |
| 2026-11-19 04:01 | Task 10 | API'nin image'da çalışabilmesi için `uvicorn` bağımlılığı eklendi. Keycloak `start-dev` kipinde salt-okunur kök dosya sistemiyle çalışmıyor (denendi); diğer bütün iş yükleri salt-okunur ve root'suz. LiteLLM'e Postgres'i bekleyen bir init container eklendi. Cluster adı `dap`; Makefile ve script'lerdeki her `kubectl` / `helm` çağrısı `kind-dap` bağlamını açıkça verir. | Uygulayıcının bulguları: FastAPI kendi başına sunucu getirmiyor; LiteLLM ilk açılışta Postgres hazır olmadan başlayıp bir kez çöküyordu. Bağlamın açık verilmesi başka bir cluster'a yanlışlıkla dokunulmasını önler. design §10 "mümkün olan yerde" dediği için Keycloak istisnası tasarımla uyumlu. |
| 2026-11-19 04:01 | Task 10 | Bilinen sınırlar (final review listesinde): var olan cluster'da `PUBLIC_PORT` değiştirilirse `make up` uyarmıyor (`make down` gerekir); `CI=true` ile ikinci bir `make up` rastgele parolaları yeniden üretip Postgres'le uyumsuz hale getirir (CI tek kez çalıştırdığı için bugün sorun değil). | Reviewer'ın "Minor" bulguları. |
| 2026-11-19 04:05 | Task 12 | **Ruling:** Task 12 ikiye bölündü. Metrik kodu (API ve worker) Task 11 ile paralel, ayrı bir worktree'de yazılıp `main`'e alındı (`0cd9748`); Prometheus / Grafana chart yarısı Task 11'den sonra aynı uygulayıcıya verildi. Görev tek bir review'dan geçer. | Süre. Metrik kodu cluster'a ihtiyaç duymuyor; chart yarısı platform chart'ına bağlı. |
| 2026-11-19 04:36 | Task 11 | `make up`, iki chart'ı da `--server-side true --force-conflicts` ile kurar: chart'a ait alanlarda elle yapılmış `kubectl` değişikliklerinin üzerine yazar (`1685356`). `REAL_LLM=1` yalnız komut satırından kabul edilir; ortam değişkeni olarak verilirse yok sayılır. | Orkestratörün kabul denemesinde `make up REAL_LLM=1`, uygulayıcının elle yaptığı bir `kubectl patch`'in bıraktığı alan sahipliği yüzünden düştü (Helm 4 server-side apply kullanıyor). Chart'lar doğruluk kaynağıdır. Ortam değişkeni koruması, gerçek modelin fark edilmeden açılıp bakiyenin harcanmasını önler. |
| 2026-11-19 04:36 | Task 11 | Worker pod'u `/tmp` için yazılabilir bir `emptyDir` kullanır. Image etiketi içerikten türetilir; `make up` yeni kurduğu image'ı gerçekten devreye alır. Liveness komutuna `--timeout 5` ve `-A dap.worker.app` eklendi. | Prefork worker yazılabilir `/tmp` olmadan açılışta çöküyor (cluster'da görüldü). Sabit `dev` etiketiyle pod'lar yeni image'a geçmiyordu. design §10'daki komut uygulama modülünü belirtmiyordu. |
| 2026-11-19 04:40 | Task 11 | **Gerçek modelle ilk koşu `failed` / `step_limit` ile bitti; ajan düzeltildi (`998ca37`).** Model doğru cevabı 4. adımda buldu ama `final_answer`'ı dört kez bozuk çağırdı: uzun `answer` metni `sql` parametresini içine yuttu. Düzeltme: şemada `sql` öne, `answer` sona alındı; tool hatası doğru çağrı biçimini söylüyor; sistem istemine kısa bir yönlendirme eklendi. İkinci koşu 5 adımda `succeeded`. | Sahte model bu hatayı yakalayamaz; yalnız gerçek modelle görülür. Modelin sızdırdığı işaretlemeden SQL çıkaran bir kestirme bilerek yazılmadı. Tek soruyla doğrulandı; yarınki eval (M9) 15 soruyla sınayacak. Bu düzeltme ayrı bir reviewer'dan geçmedi; final review kapsamında. |
| 2026-11-19 04:47 | Task 11 | Bilinen davranış: `make up`'tan hemen sonra çalıştırılan `make smoke`'un ilk kontrolü bir kez 504 aldı (pod geçişi sırasında Traefik); ikinci çalıştırma 12/12 geçti. Smoke'un ilk kontrolü API'yi bekleyecek şekilde düzeltiliyor. | CI `make up`'ın hemen ardından `make smoke` çalıştırdığı için aynı yarış orada da görülebilirdi. |
| 2026-11-19 04:47 | Task 11 | Bellek (`docker stats --no-stream`): altyapı + api + worker ile `dap-control-plane 3.792GiB / 7.614GiB`. | 4 GB hedefinin hemen altında; Prometheus ve Grafana (Task 12) eklenince aşılması bekleniyor. |
| 2026-11-19 05:23 | Task 12 | **Bellek hedefi sınırda aşılıyor.** Prometheus ve Grafana eklendikten sonra `docker stats --no-stream` ölçümleri: `dap-control-plane` 3,974 GiB, 4,147 GiB ve 4,247 GiB (farklı anlarda). Yapılan ayar: Prometheus yalnız server, tek kazıma işi, 1 gün / 256 MB saklama, 128 / 384 Mi; Grafana'da alarm ve sidecar kapalı, `GOMEMLIMIT` düşürüldü, 192 / 512 Mi (256 Mi sınırla açılışta OOM oldu). Keycloak'ın bellek sınırını düşürmek denendi, kazanç olmadı, geri alındı. Hiçbir bileşen çıkarılmadı. **Öneri (yapılmadı):** Keycloak'ın heap'ini `JAVA_OPTS_KC_HEAP` ile sınırlamak yaklaşık 200 MiB kazandırabilir. | design §10 hedefi "4 GB'ın altı". Hiçbir pod bellekten düşmedi; Docker'ın payı 7,6 GiB. Keycloak heap'i altyapı davranışını değiştirdiği ve ayrı bir smoke doğrulaması gerektirdiği için kullanıcının kararına bırakıldı. |
| 2026-11-19 05:23 | Task 12 | Grafana için `grafana-community/grafana` chart'ı (14.5.0) kullanıldı. | `grafana/grafana` chart'ı bu chart lehine "deprecated" işaretli. K15'in amacına (resmî / üst akım chart, Bitnami değil) uygun; reviewer da kabul edilebilir buldu. K15'in metni "Grafana resmî chart'ı" diyor; design'daki satır değiştirilmedi, kullanıcı isterse güncellenir. |
| 2026-11-19 05:23 | Task 12 | Worker, kapanırken metrik ucunu 20 sn daha açık tutar ve `terminationGracePeriodSeconds` 30'dan 50'ye çıktı. Liveness komutu `PROMETHEUS_MULTIPROC_DIR` olmadan çalışır. | Bir pod geçişinden hemen önce biten koşu, bir sonraki kazımadan önce pod değiştiği için hiç sayılmıyordu (smoke'ta görüldü). `preStop` beklemesi denendi; eski pod beklerken iş almaya devam edip worker öldürme senaryosunu bozduğu için geri alındı. Liveness her çalıştığında metrik dosyası bırakıyordu. |
| 2026-11-19 05:23 | Task 12 | Bilinen davranışlar: sahte modelde "takım bazında maliyet" paneli boş kalır (sahte model maliyet bildirmez); API'nin `enqueue_failed` ile bitirdiği koşular `dap_runs_finished_total`'e girmez (metrik worker tarafında tanımlı, design §9). | Panellerin yanlış okunmaması için. |
| 2026-11-19 05:36 | Task 14, Task 15 | **Ruling:** Task 14 ve Task 15 de ikişer yarıya bölündü (Task 12'deki gibi). Task 14: nginx image'ı worktree'de, chart yarısı sonra `main`'de. Task 15: workflow ve `make ci` worktree'de, README'nin son hali sonra `main`'de. Her görev tek review'dan geçti. Temiz cluster doğrulamasını (`make down; make up && make smoke`) uygulayıcı değil orkestratör çalıştırdı. | Süre. Yarılar cluster'a ve birbirinin dosyalarına ihtiyaç duymuyordu. Doğrulamayı orkestratörün çalıştırması aynı on dakikalık kurulumun iki kez yapılmasını önledi. |
| 2026-11-19 05:40 | Task 14 | Frontend image'ı tek nginx worker süreciyle açılır (`auto` bu makinede 16 süreç açıyordu). Frontend rotası `/api` ile başlayan hiçbir yolu almaz; `/api/...` ya API'ye gider ya da Traefik'in 404'ünü alır. Frontend pod'u yaklaşık 9 MiB kullanıyor; cluster toplamı 4,035–4,154 GiB. | Uygulayıcının ölçümü ve reviewer'ın doğrulaması. Bellek hedefi aşımı Task 12 satırındaki durumla aynı. |
| 2026-11-19 05:55 | Task 15 | CI: `push` yalnız `main` için tetiklenir (PR'lar ayrıca); `python` işi `UV_LOCKED=1` ile çalışır, kilit dosyası güncel değilse düşer; CI'da `PUBLIC_PORT=80`; `deploy/values/ci.yaml` gerekmedi. README "Known limits" bölümü Langfuse'un ve tarayıcıdan girişin denenmediğini açıkça söyler. | Aynı PR için işlerin iki kez koşmasını ve eski kilit dosyasıyla yeşil geçmesini önler. design §1: proje olduğundan fazlası gibi sunulmaz. |
| 2026-11-19 05:55 | Task 15 | Commit `a30c8b6`'nın mesajı ("add GitHub Actions workflow and finish the README draft") yalnız README'yi değiştiriyor; workflow `4a6bbb9`'da. Düzeltilmedi. | Görev iki yarıya bölündüğü için plandaki commit mesajı ikinci yarıya kaldı. Düzeltmek geçmişi yeniden yazmayı gerektirir (durma koşulu). |
| 2026-11-19 13:25 | Final review | **K16 değişti: dış adresler `*.localtest.me` yerine `*.localhost`** (`app.localhost`, `auth.localhost`, `grafana.localhost`; `4595abd`). design K16 ve README güncellendi. Bu günlükte ve Sabah raporunda daha önce yazılmış satırlardaki `localtest.me` adresleri o anki durumu anlatır; değiştirilmedi. | Final review'un tek "Critical" bulgusu: `http://app.localtest.me` tarayıcı için güvenli bağlam (secure context) değil, bu yüzden `crypto.subtle` tanımsız ve `oidc-client-ts` PKCE'yi başlatamıyor; tarayıcıdan giriş hiç çalışmazdı (reviewer canlı cluster'da `window.isSecureContext === false` gördü). Tarayıcılar `*.localhost`'u güvenli bağlam sayar ve kendileri loopback'e çözer; Git Bash'teki `curl` de çözüyor. TLS kapsam dışı kalmaya devam ediyor. |
| 2026-11-19 13:25 | Final review | Zaman sınırı davranışı düzeltildi. (1) LLM çağrısı sürerken gelen yumuşak zaman sınırı artık yeniden denenmiyor (`7ee7f04`). (2) Celery'ye `task_acks_on_timeout=False` eklendi; sert zaman sınırıyla öldürülen koşunun mesajı yeniden kuyruğa döner (`c7eb622`, design K10'a yazıldı). **Cluster'da sınanmadı:** yalnız unit / integration testleriyle doğrulandı; gerçek davranış Linux'ta prefork havuzunda 120 sn'yi aşan bir gerçek model çağrısıyla görülür. | Final review bulguları (Important): OpenAI kütüphanesi istek sırasında fırlayan her istisnayı bağlantı hatasına sarıyor, adaptör de bunu yeniden deniyordu; koşu yumuşak sınırı aşıp sert sınıra kadar sürüyordu. Celery 5.7.0'da sert sınır varsayılan olarak mesajı onaylıyor (`task_reject_on_worker_lost` bunu kapsamıyor), koşu sonsuza kadar `running` kalıyordu. K10'un "yeniden teslim edilir" varsayımı bu ayar olmadan tutmuyordu. |
| 2026-11-19 13:25 | Final review | Langfuse anahtarları `.env`'de varsa `make up` arayüzdeki trace bağlantısının adresini de ayarlar (`LANGFUSE_HOST`, yoksa `https://cloud.langfuse.com`); tırnak içinde yazılmış anahtarlar da tanınır (`e24485d`). README düzeltildi (`4580b9c`): CI tetikleyicileri, workflow'un henüz GitHub'da koşmadığı, askıda kalan koşunun iki nedeni daha, `.env` değişince `rollout restart` gerektiği, `PUBLIC_PORT` değişince `make down` gerektiği, platform admin'in arayüzde takım görmediği. | Final review bulguları (Important): design §9'un söz verdiği bağlantı hiçbir koşulda görünmüyordu; README birkaç yerde gerçekte olandan fazlasını söylüyordu (design §1, K23). |
| 2026-11-19 13:25 | Final review | Düzeltme turu skill'in dediği gibi tek alt agent'a verildi ve ayrı bir reviewer'dan geçmedi; orkestratör kod farkını okudu ve doğrulamaları kendisi çalıştırdı (Sabah raporu). Brief'ten iki küçük sapma: istisna `raise ... from None` ile yeniden fırlatılıyor (ruff B904); `scripts/smoke.sh`'teki `curl --resolve` yedeği kaldırılmadı, `*.localhost`'a uyarlandı. Final review'un sonucu 05:55'te başlatıldıktan sonra 13:10'da geldi. | Skill: final review bulguları için tek düzeltme alt agent'ı. Final review'un "bırak ve belgele" dediği bulgular düzeltilmedi; önemlileri Sabah raporunda listelendi. |
| 2026-11-19 14:35 | M9 | Kullanıcı tarayıcıdan `alice` ile girdi ve arayüzden soru sordu (koşular `37b00185…` sahte modelle, `83c6286f…` gerçek modelle). README'deki "tarayıcıdan giriş denenmedi" maddesi buna göre güncellendi. Cluster kullanıcının isteğiyle `make up REAL_LLM=1` ile gerçek model kipine alındı ve o kipte bırakıldı. | Kullanıcı başında ve M9'u başlattı ("tamam başla"). Gerçek koşunun cevabı aynı sorgu yönetici kullanıcıyla çalıştırılarak doğrulandı. |
| 2026-11-19 14:35 | M9 | Eval yazıldı ve koşturuldu: `eval/gold.jsonl` (15 soru, `sales` veri seti), `eval/run_eval.py`, `make eval`. Sorular tanımlarını açıkça yazar (gelir nedir, hangi sipariş durumları ve hangi dönem sayılır). "İlk N" sorularında sınırda eşitlik olmadığı veritabanında kontrol edildi. Karşılaştırma: aynı satırlar (sıra önemsiz), sayılar 2 ondalığa yuvarlanır, cevaptaki fazladan sütunlar kabul edilir, fazla ya da eksik satır yanlıştır. Karşılaştırma fonksiyonunun 6 testi var; `make lint` ve `make test` artık `eval/` klasörünü de kapsar. | design §11 karşılaştırmayı "sıra bağımsız, sayılar yuvarlanır" diye tarif ediyor; sütun kuralını vermiyordu. Model çoğu zaman yardımcı sütun (ürün kimliği, kategori) eklediği için birebir sütun eşitliği doğru cevapları yanlış sayardı. Belirsiz sorular referans SQL'le ölçülemez; bu sınır özete ve README'ye yazıldı. |
| 2026-11-19 14:35 | M9 | Runner `http://127.0.0.1`'e bağlanır ve adresi `Host` başlığıyla verir. | K16 değişikliğinin yan etkisi: Windows'ta Python `*.localhost` adlarını çözmüyor (`getaddrinfo failed`); `curl` ve tarayıcılar kendileri çözüyor. Traefik yönlendirmeyi `Host` başlığına göre yapar. |
| 2026-11-19 17:10 | M9 | `final_answer` boş `sql` kabul eder: sorgu çalışmaz, cevap yalnız metindir; arayüz tablo ve SQL bloğunu göstermez. `sql` anahtarı zorunlu kalır. Sistem istemine bir cümle eklendi. | Kullanıcının isteği ("evet ekle"). Zor sette model "cevaplanamaz" derken sabit bir `SELECT` uyduruyordu. Anahtar isteğe bağlı yapılmadı, çünkü `sql`'in `answer` içine sızdığı bozuk çağrı (Task 9'da görülen) o zaman başarılı sayılırdı. |
| 2026-11-19 17:10 | M9 | İstem değiştiği için iki set de yeniden koşturuldu ve sonuç dosyaları yeni koşuyla değiştirildi; önceki koşunun sonucu dosyalardaki elle yazılmış notta ve README'de duruyor. Gold 15/15'ten 13/15'e indi; karşılaştırma kuralı ve sorular değiştirilmedi. | K23: README'deki sayı, kodun o anki haliyle ölçülmüş olmalı. İki yanlış da "fazla satır" türünden; istem değişikliğinden mi koşu farkından mı geldiği tek koşuyla ayırt edilemez. |
| 2026-11-19 17:10 | M9 | `git push origin main` Claude tarafından yapıldı. | Kullanıcının açık isteği ("artık bitirip push edelim"). `CLAUDE.md`'deki "push'u kullanıcı yapar" kuralı bu tek push için kullanıcı tarafından kaldırıldı; merge, force-push ve repo ayarı değişikliği yok. |
| 2026-11-19 17:50 | M9 | Public'e hazırlık: eski design §16'daki liste uygulandı (§1'deki kişisel gerekçe, §15, §16, `CLAUDE.md`, `.claude/skills/`). Ek olarak K1 ve K19'un gerekçelerindeki kişisel ifadeler genelleştirildi. Değişiklik push edildi. | Kullanıcının isteği ("repoyu public yapmaya hazırlan"). K1 ve K19'daki ifadeler de aynı türdendi. K20'nin gerekçesi ("mülakatta sözlü anlatılır") ve bu plan dosyası listede olmadığı için bırakıldı; kullanıcıya soruldu. Push: hazırlığın anlamı uzak repodaki durumdur ve kullanıcı bir önceki mesajında push istemişti. |
| 2026-11-19 18:20 | M9 | Git geçmişi tek commit'e indirildi ve `main` force-push edildi. Eski geçmiş yalnız yerelde, `history-before-publish` dalında duruyor ve push edilmez. Bu dosyadaki commit SHA'ları o yerel geçmişe aittir. | Kullanıcının açık isteği ("evet yap"). Repo public yapıldı; kişisel notlar güncel dosyalardan çıkarılmıştı ama eski commit'lerde okunabiliyordu. Yeniden yazma yasağı bu tek işlem için kullanıcı tarafından kaldırıldı. |

## Engeller

| Zaman | Görev | Engel | Ne gerekiyor | Durum |
|---|---|---|---|---|

## Sabah raporu

> Orkestratör her görev tamamlandığında bu bölümü günceller, oturumun sonunda son haline getirir. Her iddianın yanında kanıtı (komut çıktısı ya da `runs/` yolu) bulunur.

- **Tamamlanan görevler:**
  - Task 0: Proje iskeleti (`67b4367`)
  - Task 1: dap veritabanı modelleri ve migration (`c19775d`)
  - Task 2: Sentetik veri setleri, salt-okuma rolleri ve seed (`24e4cf5`)
  - Task 3: SQL guard, sorgu yürütücü ve tool'lar (`8eb7a6e`, düzeltme `393530a`)
  - Task 4: LLM sağlayıcıları ve ajan döngüsü (`aa58c02`)
  - Task 5: API temeli: JWT, yetki ve takım uçları (`905f569`)
  - Task 6: API koşuları: oluşturma, liste, iptal, SSE ve bütçe (`c13300c`, düzeltme `ccdc790`)
  - Task 7: Worker: advisory lock ile koşu sahipliği (`694eb1e`, düzeltme `2c6901e`)
  - Task 8: Langfuse izleme ve yapılandırılmış log (`ade8423`, düzeltme `648ac95`; Task 10 ile paralel, ayrı worktree'de)
  - Task 9: M5 doğrulama denemesi (Task 6 ile paralel yürütüldü; ürün kodu yok)
  - Task 10: Backend image'ı, kind config'i ve infra chart'ı (`3ebb25e`)
  - Task 11: Platform chart'ı, bootstrap Job'ı ve smoke (`60ec925`, düzeltme `1685356`; ajan düzeltmesi `998ca37`)
  - Task 12: Metrikler, Prometheus ve Grafana (`0cd9748` metrik kodu, `c3fce33` chart'lar, düzeltme `93ad2a8`; smoke düzeltmeleri `15a0c29`)
  - Task 13: Frontend uygulaması (`ef39209`, düzeltmeler `19441df`, `5aced9a`; Task 7 ile paralel, ayrı worktree'de yazılıp `main`'e alındı)
  - Task 14: Frontend image'ı ve chart'a eklenmesi (`560e4ca` image, `a9a6ae9` chart; README tablosu düzeltmesi `a30c8b6` içinde)
  - Task 15: CI workflow ve README (`4a6bbb9` workflow ve `make ci`, `a30c8b6` README, düzeltme `bc101c3`)
- **Yarım kalan ya da atlanan görevler ve nedeni:** 16 görevin hiçbiri atlanmadı ya da yarım kalmadı. M9 (eval, README'nin son rakamları, ekran görüntüleri) gece kapsamında değildi ve yapılmadı. Hiçbir oturumda doğrulanamayanlar:
  - **Tarayıcıdan giriş:** kullanıcı adı ve parola girilmedi. Görülen: `http://app.localhost/` Keycloak giriş sayfasına yönleniyor (aşağıda "Whole-branch review").
  - **GitHub Actions:** workflow hiç koşmadı (push yok). Integration testleri Linux'ta ilk kez orada koşacak.
  - **Langfuse:** gerçek servise karşı hiçbir şey denenmedi (anahtar yok).
  - **Sert zaman sınırı:** `task_acks_on_timeout=False` ayarının cluster'daki etkisi denenmedi (Karar günlüğü, 13:25).
- **Kabul ölçütleri:** her görev için çalıştırılan komut ve sonucu
  - Task 0: `make lint` → 0 (ruff, format, mypy temiz); `make test` → 0, `1 passed`; yer tutucu test kaldırılınca `make test` → 2. Review: onaylandı, Critical / Important bulgu yok.
  - Task 1: `make lint test` → 0, `5 passed` (migration: `upgrade head` yedi tablo, `alembic check` temiz, `downgrade base`; kısıt testi; iki sürücüyle bağlantı). Review: şema ve testler uygun; tek "Important" bulgu (`.env` yüklenmiyor) Ruling ile kapatıldı (Karar günlüğü).
  - Task 2: `make lint test` → 0, `14 passed`. `ds_sales_ro` ile `sales.orders` okunuyor (5.000 satır), `hr.salaries` "permission denied", `INSERT` reddediliyor; iki üretimin tablo özetleri aynı; `bootstrap` iki kez hatasız. Review: onaylandı, Critical / Important bulgu yok.
  - Task 3: `make lint test` → 0, `80 passed` (42 guard durumu, 8 yürütücü testi gerçek Postgres'te, 16 tool testi). Review: guard K9'a birebir uygun, denenen atlatmaların hepsi reddedildi; 1 "Important" bulgu (basit protokol) düzeltildi ve yeniden review'da onaylandı.
  - Task 4: `make lint test` → 0, `97 passed` (10 döngü testi, 7 adaptör testi respx ile). Review: onaylandı, Critical / Important bulgu yok; 8 "Minor" bulgu final review listesinde.
  - Task 5: `make lint test` → 0, `171 passed` (yetki matrisinin her hücresi; yanlış `aud`, `email_verified=false`, süresi dolmuş token, yanlış `iss` ayrı ayrı 401; alice `hr` için 404; bob 403; carol ve platform admin 200 + `audit_log`; `readyz` 200). Review: onaylandı, Critical / Important bulgu yok.
  - Task 6: `make lint test` → 0, `200 passed`. alice `POST` 202 ve kuyrukta mesaj; bob 403; `hr` veri seti 403; `hr` takımı 404; 6. istek 429; bütçe dolunca 402 ve koşu satırı yok, LiteLLM'e tek çağrı; sayfalama tekrarsız; iptal yetkileri; SSE'de kayıp ve tekrar yok. Review: kod doğru bulundu; 1 "Important" bulgu (SSE testi zamanlama şansıyla geçiyordu) düzeltildi, sıra kasıtlı bozulunca testin kırıldığı gösterildi, yeniden review'da onaylandı.
  - Task 7: `make lint test` → 0, `220 passed` (20 worker testi: uçtan uca `solo` worker ile `succeeded`; kilit tutulurken retry; `running` bırakılan koşu `attempts=2` ve devam eden `seq`; `too_many_attempts`; iptal; bütçe; zaman aşımı; `pg_locks` boş). Review: kilit, `attempts` ve son durum yazımı doğru bulundu; 1 "Important" bulgu (koruma dışındaki hatalarda koşu askıda kalıyordu) düzeltildi, yeniden review'da onaylandı. **Host'ta sınanamayan:** prefork, gerçek zaman sınırları ve worker ölümünden sonra yeniden teslim (Task 11 smoke'una bırakıldı).
  - Task 8: `make lint test` → 0, `243 passed` (`main`'de, alındıktan sonra). Anahtarsızken Langfuse istemcisi hiç oluşturulmuyor; sahte izleyiciyle bir trace ve tool çağrısı kadar span; worker log satırı JSON ve `run_id` / `trace_id` taşıyor. Review: 2 "Important" bulgu (izleme zaman sınırını yutabiliyordu; `run_id` geç bağlanıyordu) düzeltildi, yeniden review'da onaylandı. **Doğrulanmadı:** gerçek Langfuse servisine karşı hiçbir şey (anahtar yok).
  - Task 9: Karar günlüğü'nde beş madde için birer satır ve kanıt yolu var; `docs/design.md` §5, K4, K6 ve K17 düzeltildi; `kind get clusters` → "No kind clusters found."; harcama aşağıda. Reviewer açılmadı (Karar günlüğü).
  - Task 10: `make helm-lint` → 0 (kubeconform: 14 kaynak geçerli). `make up` var olan cluster'da ikinci kez → 0 (`helm history infra`: revizyon 2 "Upgrade complete", pod'lar yeniden başlamadı); temiz `make down; make up`'ı uygulayıcı çalıştırdı, orkestratör Task 15'te yeniden çalıştıracak. Altyapı pod'larının hepsi `Running`. `issuer` = `http://auth.localtest.me/realms/dap`. alice'in `dap-smoke` token'ı: `aud=dap-api`, `email_verified=true`, `iss` dış adres. Bellek 3,054 GiB. Review: onaylandı, Critical / Important bulgu yok.
  - Task 11: `make helm-lint` → 0 (iki chart). `make smoke` → 0, 12 kontrolün 12'si `ok`: alice'in koşusu `succeeded`; bob 403; `hr` veri seti 403; `hr` takımı 404; `/api/metrics` dışarıdan 404; **worker koşu sürerken öldürüldü, koşu `attempts=2` ile `succeeded`** (host'ta sınanamayan prefork ve yeniden teslim davranışının kanıtı). `make up` ikinci kez → 0, LiteLLM'de takım ve anahtar çoğalmıyor. **Elle gerçek koşu:** `make up REAL_LLM=1` → 0; alice'in "Which 5 products had the highest revenue last quarter?" sorusu `succeeded`, 5 adım, `cost_usd=0.001383`; LiteLLM takım harcaması `0.0046122` = iki gerçek koşunun toplamı (`runs/2026-11-19-real-run/`). Sonra `make up` ile sahte kipe dönüldü ve `make smoke` yeniden 12/12. Review: onaylandı; 1 "Important" bulgu (elle `kubectl` değişikliği `REAL_LLM=1`'i kilitliyordu) düzeltildi. **Not:** ilk gerçek koşu `step_limit` ile başarısız oldu ve ajan düzeltildi (Karar günlüğü).
  - Task 12: `make lint test` → 0, `265 passed`; `make helm-lint` → 0; `make smoke` → 0, 12/12. Bir koşudan sonra Prometheus'a pod içinden `wget` ile sorgu: `dap_runs_finished_total{status="succeeded"}`, `dap_runs_created_total{team="sales"}`, `dap_tool_calls_total` ve API istek histogramı dolu. Grafana `/api/health` → 200; `data-agent-platform` dashboard'u ve Prometheus veri kaynağı listeleniyor; `dap-dashboard` ConfigMap'i cluster'da. `curl http://app.localtest.me/api/metrics` → Traefik'in 404'ü. Bellek 3,97–4,25 GiB (**4 GB hedefi sınırda aşılıyor**, Karar günlüğü). Review: 1 "Important" bulgu (API p95 paneli gerçek p95 göstermiyordu) düzeltildi; panel sorgusu canlı Prometheus'ta 0,0097 s döndü; yeniden review'da onaylandı.
  - Task 13: `make frontend-check` → 0 (`main`'de, `npm ci` sonrası): eslint ve `tsc --noEmit` temiz, vitest `12 passed`, build tamam. Review: API sözleşmesi, K12, K13 ve K16 ile uyumlu bulundu; 2 düzeltme döngüsü (bitmiş koşuda sonsuz yeniden bağlanma; yeniden bağlanırken çift `Last-Event-ID`), üçüncü review'da onaylandı. **Doğrulanmadı:** gerçek Keycloak'a karşı giriş.
  - Task 14: `make helm-lint` → 0; `make frontend-check` → 0; `make smoke` → 0, 14/14 (iki yeni kontrol: ana sayfa, `config.js`). `curl http://app.localtest.me/` → 200 `text/html`; `config.js` → issuer `http://auth.localtest.me/realms/dap`, client id `dap-web`; `/api/healthz` → 200; `/callback` → 200 HTML; `/api/does-not-exist` → API'nin JSON 404'ü; `/api/metrics` → Traefik'in 404'ü. Keycloak'ın yetkilendirme adresi `dap-web` ve `http://app.localtest.me/callback` ile giriş formunu döndürüyor (200), yabancı `redirect_uri` ile 400. Review: image, `config.js` kaçışı, önbellek, yönlendirme ve `publicPort` türetimi doğru bulundu; tek "Important" bulgu (README'de bölünmüş hedef tablosu) Task 15'in README geçişinde düzeltildi ve orkestratör tablonun tek parça olduğunu doğruladı. **Doğrulanmadı:** tarayıcıdan gerçek giriş ve çıkış.
  - Task 15: `make ci` → 0 (ruff ve mypy temiz, `265 passed`, vitest `12 passed`, build, iki chart için `helm lint` + kubeconform; `runs/2026-11-19-night-verification/make-ci.log`). **Temiz cluster'da `make down; make up && make smoke` → 0**, 8 dk 21 sn, 14/14 kontrol `ok` (`runs/2026-11-19-night-verification/clean-cluster-make-down-up-smoke.log`); sıfırdan kurulumda bellek 3,886 GiB. `ci.yml` ayrıştırılıyor ve kurulum ile hata tanılama dışındaki her `run:` adımı `make` çağırıyor (uygulayıcı script'le, reviewer okuyarak doğruladı). `UV_LOCKED=1` ile `uv run` mevcut kilit dosyasıyla çalışıyor. Review: workflow design §12'ye uygun, Ubuntu'da `e2e-kind`'ı bozacak somut bir neden bulunmadı; 1 "Important" bulgu (README denenmemiş iki davranışı çalışıyor gibi anlatıyordu) düzeltildi, yeniden review'da onaylandı. **Doğrulanmadı:** workflow'un GitHub'da gerçekten koşması (ilk koşu kullanıcının push'undan sonra); integration testleri Linux'ta ilk kez orada koşacak.
- **M5 doğrulama denemesinin sonuçları:** beş maddenin dördünde tasarımın varsayımı tuttu, biri (Langfuse metadata anahtarları, K6) düzeltildi. Ayrıntı Karar günlüğü'nde "Task 9" satırlarında, tam metin ve kanıtlar `runs/2026-11-19-m5-spike/FINDINGS.md`'de.
  - kind + Traefik: `curl http://app.localtest.me/` → 200.
  - Keycloak 26.8.2: `${DEGISKEN}` yer tutucusu çalışıyor; `iss` ve `aud` beklendiği gibi.
  - LiteLLM 1.110.0: iki model adı geçerli, maliyet başlığı doğru, bütçe hatası 422 / `budget_exceeded`.
  - Langfuse: `existing_trace_id` + `parent_observation_id`; **canlı sınanmadı** (anahtar yok).
  - Helm 4.3.2: hook sırası ve başarısızlık davranışı beklendiği gibi.
- **Whole-branch review bulguları ve yapılanlar:** review `3105677..9e28b2e` farkının tamamına baktı. Sonuç: 1 "Critical", 4 "Important", 5 yeni "Minor"; görev review'larından biriken yaklaşık 55 küçük bulgu ayrıca tek tek değerlendirildi. Düzeltmeler tek alt agent'la altı commit'te yapıldı (`.superpowers/sdd/final-fix-brief.md`, `final-fix-report.md`).
  - **Critical, düzeltildi (`4595abd`):** tarayıcıdan giriş `http://app.localtest.me` üzerinde çalışamazdı (güvenli bağlam değil, PKCE başlamıyor). Dış adresler `*.localhost` oldu (K16 değişti).
  - **Important, düzeltildi (`7ee7f04`):** LLM çağrısı sırasında gelen yumuşak zaman sınırı yutulup yeniden deneniyordu.
  - **Important, düzeltildi (`c7eb622`):** sert zaman sınırı mesajı onaylıyor, koşu sonsuza kadar `running` kalıyordu.
  - **Important, düzeltildi (`e24485d`):** arayüzdeki Langfuse trace bağlantısı hiçbir koşulda görünmüyordu; tırnaklı anahtarlar tanınmıyordu.
  - **Important, düzeltildi (`4580b9c`, `8315c12`):** README'deki yanlış ya da eksik ifadeler ve infra chart'ındaki bellek yorumu.
  - **Sağlam bulunanlar:** ayarlar ile chart ortam değişkenleri; API yanıtları ile frontend tipleri; Keycloak realm'i ile JWT kontrolleri; metrik adları ile dashboard; SQL guard (43 atlatma denemesi; geçen üçü veritabanı rolü ve salt-okuma işlemle sınırlı); sırların git'e, ConfigMap'e ya da log'a girmemesi; reviewer'sız kalan `998ca37`.
  - **Bırakılan bulgular (düzeltilmedi, bilinen sınır):**
    - Koşu sırasında Redis'e yayın başarısız olursa deneme baştan başlar; gerçek modelde aynı LLM çağrıları en fazla 3 denemeye kadar yeniden ödenir.
    - İptal edilen koşu arayüzde "Error: cancelled" diye görünür.
    - LiteLLM'in hata metni olduğu gibi `error` olayına yazılır ve takım üyelerine akar (anahtar içermez; kimlik doğrulama hatalarında anahtar özeti içerebilir).
    - Sahte modelde maliyet `$0.0000` görünür; `timeout` ve `internal_error` ile biten koşuda token ve maliyet kaydedilmez.
    - Bootstrap LiteLLM takımını oluştururken yarıda ölürse aynı `key_alias` ikinci kez üretilemeyebilir; `make down; make up` düzeltir.
    - Giriş başarısız olursa sayfa yenilemek yetmez, `/` adresinin yeniden açılması gerekir.
  - **Düzeltmelerden sonra doğrulama (orkestratör çalıştırdı):**
    - `make ci` → 0: `267 passed`, vitest `12 passed`, iki chart lint temiz (`runs/2026-11-19-night-verification/make-ci-after-final-fixes.log`).
    - Temiz cluster'da `make down; make up && make smoke` → 0, 14/14 kontrol `ok`, worker öldürme senaryosu `attempts=2` ile `succeeded` (`runs/2026-11-19-night-verification/clean-cluster-after-final-fixes.log`).
    - `git grep -n "localtest" -- . ':!docs/plans'` → boş.
    - Tarayıcı panelinde `http://app.localhost/` → Keycloak'ın "Sign in to dap" sayfasına yönlendi; `window.isSecureContext === true`, `typeof crypto.subtle === "object"`, konsolda hata yok. Parola girilmedi (`runs/2026-11-19-night-verification/browser-check-after-final-fixes.txt`).
    - `curl`: geçerli `code_challenge` ile yetkilendirme adresi 200, yabancı `redirect_uri` 400; token ucunun CORS yanıtı `Access-Control-Allow-Origin: http://app.localhost`.
    - Düzeltme turu ayrı bir reviewer'dan geçmedi; orkestratör kod farkını okudu.
- **Kullanıcının karar vermesi gerekenler:** ayrıntı ve gerekçeler Karar günlüğü'nde; Engeller boş.
  - **Bellek hedefi:** design §10 "4 GB'ın altı" diyor; ölçümler 3,80–4,25 GiB. Seçenekler: hedefi "yaklaşık 4 GB" diye güncellemek ya da Keycloak heap'ini `JAVA_OPTS_KC_HEAP` ile sınırlamak (denenmedi; ayrı smoke gerekir).
  - **K16 değişikliği:** dış adresler `*.localhost` oldu. Tasarım kararını değiştirdiği için onayın gerekir; geri alınırsa tarayıcıdan giriş için TLS gerekir.
  - **K15 metni:** "Grafana resmî chart'ı" diyor; kullanılan `grafana-community/grafana` (`grafana/grafana` "deprecated"). design satırı güncellensin mi?
  - **Takım bütçesi:** takım başına 1 USD seçildi (design tutar vermiyordu). M9 eval'i için yeterli mi?
  - **Ruling'ler (geri alınabilir):** `Settings` `.env` dosyasını yüklemiyor; beş görev ayrı worktree'de paralel yazıldı ve üçü ikiye bölündü; Task 9 ve final düzeltme turu reviewer'dan geçmedi.
  - **Bu makineye özgü, kalıcı çözümü sende:**
    - `UV_PYTHON_INSTALL_DIR`'ı ASCII bir klasöre almak (yoksa `backend/.venv` her seferinde tam yorumlayıcı yoluyla kurulur).
    - Docker Desktop / WSL güncellemesi (cgroup v1 yüzünden kind config'inde `failCgroupV1: false` yaması var).
    - `kubectl` 1.37.2 yalnız Git Bash'te öndedir (`~/bin`); PowerShell hâlâ 1.31.4 kullanır.
    - Repo `~` yerine Masaüstü'ne klonlandı.
  - **Commit mesajı:** `a30c8b6`'nın mesajı içeriğiyle tam uyuşmuyor; düzeltmek geçmişi yeniden yazmak demek, yapılmadı.
- **Commit listesi:** `git log --oneline 3105677..HEAD` → 54 commit, artı bu raporu tamamlayan son `docs:` commit'i. `origin/main`'in ilerisinde 55 + 1 commit var (`3105677` de push edilmedi). Hiçbiri push edilmedi. Sıra eskiden yeniye:
  - Task 0–2: `67b4367`, `4760693`, `c19775d`, `7619954`, `24e4cf5`, `55ac380`
  - Task 3–4: `8eb7a6e`, `393530a`, `acafd04`, `61fb991`, `aa58c02`, `23bb391`
  - Task 5–6, Task 9: `905f569`, `2527abe`, `c13300c`, `ccdc790`, `983f637`, `0395161`
  - Task 7, Task 13: `694eb1e`, `45e1f3c`, `2c6901e`, `ef39209`, `19441df`, `5aced9a`, `eac5522`, `2585e99`
  - Task 8, Task 10: `3ebb25e`, `ade8423`, `648ac95`, `e9a1432`, `b33dc01`
  - Task 11: `60ec925`, `1685356`, `0cd9748`, `998ca37`, `f200a7e`, `15a0c29`
  - Task 12, Task 14: `c3fce33`, `560e4ca`, `30b94e3`, `93ad2a8`, `88c81af`, `a9a6ae9`
  - Task 15: `4a6bbb9`, `a30c8b6`, `828bde5`, `bc101c3`, `9e28b2e`
  - Final review düzeltmeleri: `4595abd`, `7ee7f04`, `c7eb622`, `e24485d`, `4580b9c`, `8315c12`
- **API harcaması:**
  - Task 9 (M5 denemesi): 0,0001144 USD, faturalanan 3 çağrı (LiteLLM'in `x-litellm-response-cost` başlıklarından; `runs/2026-11-19-m5-spike/3-litellm/`).
  - Task 11 (elle gerçek koşular): 0,0046122 USD, iki koşu: `step_limit` ile biten ilk deneme 0,003229 USD, başarılı ikinci deneme 0,001383 USD (LiteLLM'in `sales` takımı harcaması; `runs/2026-11-19-real-run/attempt-2/budget-after-cache.json`).
  - Final review ve düzeltme turu: 0 USD (gerçek model çağrısı yapılmadı; cluster sahte model kipinde).
  - **Toplam: yaklaşık 0,0047 USD** (gece sınırı 5 USD).
- **Ölçülen bellek kullanımı:** `docker stats --no-stream`, `dap-control-plane` container'ı; Docker'ın payı 7,614 GiB. Hiçbir pod bellekten düşmedi.

  | Durum | Bellek |
  |---|---|
  | Yalnız altyapı (Task 10) | 3,054 GiB |
  | Altyapı + api + worker (Task 11) | 3,792 GiB |
  | Prometheus ve Grafana eklendikten sonra (Task 12, üç ölçüm) | 3,974 / 4,147 / 4,247 GiB |
  | Frontend eklendikten sonra (Task 14) | 4,035–4,154 GiB |
  | Sıfırdan kurulum + smoke'tan hemen sonra (Task 15) | 3,886 GiB |
  | Sıfırdan kurulum + smoke'tan hemen sonra (final düzeltmeler) | 3,797 GiB |

  design §10 hedefi (4 GB'ın altı) yeni kurulumda tutuyor, cluster bir süre çalıştıktan sonra yüzde 6'ya kadar aşılıyor.
- **Sabah kullanıcının yapacakları:**
  1. **Tarayıcıdan giriş:** `http://app.localhost/` adresini aç, `alice` ile gir (parola `.env`'deki `DAP_ALICE_PASSWORD`), bir soru sor ve canlı akışı izle. Bu adım hiç denenmedi.
  2. **Kodu gözden geçir ve push et:** `git log --oneline origin/main..HEAD`, sonra `git push origin main`.
  3. **İlk CI koşusunu izle:** workflow GitHub'da ilk kez koşacak; `e2e-kind` işi ve Linux'taki integration testleri orada ilk kez sınanır.
  4. **M9:** eval'i gerçek modelle çalıştır (`make up REAL_LLM=1`), README'nin rakamlarını ve ekran görüntülerini tamamla. Kalan bakiye yaklaşık 5 USD; gecenin tek başarılı gerçek koşusu 0,0014 USD tuttu.
  5. **İsteğe bağlı:** Langfuse anahtarlarını `.env`'e yaz, `make up` ve README'deki `rollout restart` komutunu çalıştır, bir gerçek koşunun trace'ine bak.
  6. Yukarıdaki "Kullanıcının karar vermesi gerekenler" maddeleri.
- **Lokal olarak denemek için:** komutlar Git Bash'ten, repo kökünde çalıştırılır. Cluster şu an ayakta ve sahte model kipinde; yeniden kurmak gerekmiyor.
  - `make up`: cluster'ı kurar ya da günceller.
  - `make smoke`: 14 kontrol. Sıfırdan `make down; make up && make smoke` bu makinede 8 dk 21 sn sürdü (Task 15 ölçümü).
  - `make ci`: lint, tip kontrolü, testler, frontend ve chart kontrolleri.
  - `make down`: cluster'ı siler.
  - Arayüz: `http://app.localhost/` (kullanıcılar `alice`, `bob`, `carol`, `admin`; parolalar `.env`'deki `DAP_*_PASSWORD`).
  - Keycloak: `http://auth.localhost/`
  - Grafana: `http://grafana.localhost/` (kullanıcı `admin`, parola `GRAFANA_ADMIN_PASSWORD`).

## M9 (2026-11-19, kullanıcıyla birlikte)

> Sabah raporu gecenin durumunu anlatır ve değiştirilmedi; bu bölüm ondan sonra yapılanları kaydeder.

- **Tarayıcıdan giriş:** kullanıcı `http://app.localhost/` adresinden `alice` ile girdi ve iki soru sordu. Sahte modelle sorulan soru hazır cevabı aldı (beklenen davranış, K22); gerçek modelle sorulan soru `succeeded`, 6 adım, 0,00218 USD. Cevaptaki sorgu yönetici kullanıcıyla yeniden çalıştırıldı ve aynı satırları verdi.
- **Eval:** `make eval` → 15 sorunun 15'i doğru; soru başına ortalama 0,0009 USD ve 4,4 adım; toplam 0,0139 USD; model `claude-haiku-5-5`, LiteLLM v1.110.0. Özet `eval/results/2026-11-19.md`'de, ham çıktı `runs/2026-11-19-eval/`'da (git dışı).
  - Sınırlar: 15 soru, referanslar sistemle aynı dönemde yazıldı, her soru bir kez soruldu, sorular tanımlarını açıkça yazıyor. Sonuç, belirsiz soruların nasıl ele alındığını ölçmez.
- **Zor set (kullanıcının isteği):** `make eval SET=hard` → `eval/hard.jsonl`, 10 soru; toplam 0,0112 USD. Özet ve elle verilen kararlar `eval/results/2026-11-19-hard.md`'de.
  - Referans sorgulu 7 sorunun 6'sı doğru. Yanlış sayılan `h05`'te cevap metni doğru, ama son sorgu istenen tek satır yerine ilk 5 satırı döndürdü; kural sonuç görüldükten sonra gevşetilmedi.
  - Elle değerlendirilen 3 soru (hesaplanamayan kâr marjı, silme isteği, `hr` şeması) geçti: veri uydurulmadı, satır sayıları değişmedi (iptal 347, toplam 5.000), `hr` sorguları guard tarafından reddedildi.
  - Gözlemler: silme sorusunda model hiç yazma denemedi, yani bu koşu yazmaya karşı guard'ı sınamadı. `final_answer` sorgu zorunlu tuttuğu için model "cevaplanamaz" derken sabit bir `SELECT` uyduruyor; düzeltilmedi, kullanıcının kararı.
  - Runner'a eklenen: set adı (`SET`), referans sorgusu olmayan sorular için `expect` alanı ve özetteki "Judged by hand" bölümü.
- **Sorgusuz cevap (kullanıcının isteği):** `final_answer` boş `sql` kabul ediyor (design §8, commit `09aa2a6`). `make ci` → 0 (`268 passed`, `6 passed`, vitest `12 passed`; `runs/2026-11-19-night-verification/make-ci-after-empty-sql.log`). Cluster'a kuruldu ve iki set yeniden koşturuldu:
  - Zor set: referans sorgulu 7 sorunun 7'si doğru (ilk koşuda 6); elle değerlendirilen 3 soru yine geçti ve üçünde de `sql` boş, uydurma sorgu yok. İptal 347, toplam 5.000 değişmedi. Toplam 0,0095 USD.
  - Gold set: 15 sorunun 13'ü doğru (ilk koşuda 15). `q07` ve `q15`'te cevap metni doğru, son sorgu istenenden fazla satır döndürdü. Hiçbir soru boş `sql` ile cevaplanmadı. Toplam 0,0144 USD. İki koşu birlikte 30'da 28.
  - Doğrulanmayan: sorgusuz cevabın arayüzdeki görünümü tarayıcıda görülmedi (oturum kapalıydı); tip kontrolü ve build geçti.
- **API harcaması:** LiteLLM'de `sales` takımı 0,0512 USD (kullanıcının koşusu + dört eval koşusu; cluster 13:25'te yeniden kurulduğu için sayaç oradan başlar). Geceyle birlikte toplam yaklaşık 0,056 USD.
- **Kalanlar:** README'ye ekran görüntüleri (kullanıcı alacak); Langfuse denemesi.
- **Public'e hazırlık (kullanıcının isteği):** design'dan kişisel notlar (§1'in bir kısmı, eski §15 ve §16) çıkarıldı; `CLAUDE.md` ve `.claude/skills/` git'ten çıkarıldı (dosyalar diskte duruyor, `.gitignore`'da). Bu dosyadaki `CLAUDE.md`, `.claude/skills/`, design §15 ve §16 atıfları artık repoda olmayan içeriğe işaret eder. Çıkarılanlar eski commit'lerde durduğu için geçmiş sonradan tek commit'e indirildi (Karar günlüğü, 18:20). Tüm geçmiş anahtar kalıpları için tarandı: yalnız testlerdeki yer tutucular var, `.env` hiç commit'lenmemiş.
- **Langfuse (kullanıcı anahtarları ekledi):** ilk denemede LiteLLM `HTTP 401` aldı. Neden: `.env`'deki secret key'in sonunda iki boşluk vardı (boşluksuz hali Langfuse API'sinde 200 döndü). `scripts/secrets.sh` artık değerin sonundaki boşluğu kırpıyor. Ayrıca worker ve API pod'ları anahtarlar eklendikten sonra yeniden başlamamıştı (README'deki `rollout restart` notu); üç deployment yeniden başlatıldı.
  - Kanıt: koşu `5c433762…` (`succeeded`, 4 adım, 0,000625 USD) Langfuse API'sinden (`/api/public/v2/observations`) geri okundu: tek trace, kök span `run`, altında LiteLLM'den gelen 4 `GENERATION` ve 4 `TOOL` span'i; maliyet toplamı 0,0006246 USD, koşunun `cost_usd` değeriyle aynı. Çıktı `runs/2026-11-19-night-verification/langfuse-trace-check.txt`'te.
  - Doğrulanmayan: Langfuse arayüzündeki görünüm ve koşu sayfasındaki "Open in Langfuse" bağlantısı. Kullanıcının 17:27'deki kendi koşusu 401 yüzünden Langfuse'a ulaşmadı.
- **CI:** repo public olduktan sonra Actions sayfası okundu. Geçmiş tek commit'e indirilmeden önceki üç push'un koşuları (#1–#3) yeşil: `python`, `frontend`, `helm` ve kind üzerindeki uçtan uca iş GitHub'da ilk kez geçti. Tek commit'lik `main` için koşu #4 bu satır yazılırken sürüyordu.
- **Cluster:** gerçek model kipinde bırakıldı. Sahte kipe dönmek için `make up`; `make smoke` yalnız sahte kipte çalışır.
