# 운영 서버(EC2) 평일 장중 가동

개장일에만, 장중에만 서버를 켠다. 부팅하면 먼저 main 의 새 커밋을 검증해 반영하고, 트레이더를 띄운 뒤, 바뀐 접속 주소를 이메일(SNS)로 보낸다. **배포는 `git push` 하나로 끝나고, 다음 날 08:20 에 반영된다.**

```
EventBridge Scheduler  평일 08:20 KST ──► EC2 Start
                                           │ 부팅
                                           ▼
             systemd stock-trade.service
                │ ExecStartPre
                ▼
             scripts/update_code.py ──► fetch origin/main → 임시 worktree 에서 회귀 테스트(서버 Python)
                                        → 통과하면 ff 반영 / 아니면 기존 코드 유지 (기동은 막지 않음)
                │ ExecStart
                ▼
             start.sh (트레이더 + 대시보드)
                                           │ ExecStartPost
                                           ▼
             scripts/boot_notify.py ──► 대시보드 health 확인 → 공인 IP → 이메일(SNS)·텔레그램
                                        (휴장일이면 5분 뒤 스스로 종료)
EventBridge Scheduler  평일 15:40 KST ──► EC2 Stop ──► systemd 가 stop.sh 실행
```

## 시각을 이렇게 잡은 이유

- **08:20 기동**: 부팅과 `pip` 동기화에 1~2분이 걸린다. 장전 준비 시각(`pre_market_open_time` = 08:30) 전에 뜨면 트레이더는 준비를 미뤄 두었다가 08:30 에 새 데이터로 한다(`core/trader.py` 의 `prep_date`). 그래서 동작은 상시 가동일 때와 같다.
- **15:40 종료**: 정규장 마감(15:30) 후 10분 여유를 둔다. 운영은 당일 마감 청산을 하지 않아(`short_term_close_at_market_end` = OFF) 포지션을 다음 날로 넘기지만, 포지션은 증권사 계좌에 있으니 서버를 꺼도 상관없다.
- **휴장일**: cron 으로는 KRX 휴장일을 거를 수 없다. 그래서 부팅 후 `boot_notify` 가 KIS 휴장일 달력으로 판별해 스스로 끈다. 조회에 실패하면 개장일로 간주하므로, 이 경로 때문에 거래일을 놓치지는 않는다.

## 1회 설정

### 1. 서버 시간대 · 서비스 등록 (EC2 에서)

```bash
sudo timedatectl set-timezone Asia/Seoul

cd ~/codes/stock_trade && git pull
sudo cp deploy/stock-trade.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable stock-trade

# 지금 손으로 띄워 둔 트레이더가 있으면 내리고 systemd 로 다시 띄운다.
./stop.sh
sudo systemctl start stock-trade
systemctl status stock-trade      # active (exited) 이면 정상 — start.sh 는 띄우고 끝나는 구조
```

## 배포

**`git push origin main` 만 하면 다음 날 08:20 부팅 때 반영된다.** 아침 메일에서 결과를 확인한다.

| 메일 | 의미 |
|---|---|
| 제목 `... [new 6c375f6]` · 본문 `🔄 코드 갱신 0ef9ab6 → 6c375f6 (2커밋, 회귀 11종 통과)` | 반영됨 |
| 본문 `코드 최신 6c375f6` | 새 커밋 없음 |
| 제목 `[update REJECTED]` · 본문 `⚠️ 코드 갱신 거부 — _test_x.py 실패 — ...` | 서버 Python 에서 회귀 실패. **기존 코드로 기동했다** — 고쳐서 다시 push |
| 제목 `[update FAILED]` · 본문 `⚠️ 코드 갱신 안 됨 — ...` | fetch 실패 · 서버에 커밋 안 된 수정 · 서버에만 있는 커밋. 기존 코드로 기동했다 |
| 본문 `⚠️ systemd 유닛 파일이 바뀜` | `deploy/stock-trade.service` 를 고친 커밋은 유닛만 수동 반영해야 한다(유닛은 기동 전에 이미 읽힘) |

- **검증 게이트**: 새 커밋을 임시 worktree 에 꺼내 **서버 venv 의 Python(3.11)** 으로 그 커밋의 `scripts/_test_*.py` 전부를 돌린다(현재 11종, 수 초). `requirements.txt` 가 바뀌었으면 pip 설치가 먼저다. 테스트는 임시 worktree 안에서 돌아 운영 `data/` · `logs/` 를 건드리지 않는다.
- **게이트가 못 막는 것**: 테스트가 잡는 건 **고장**뿐이다. 테스트를 통과하는 전략 동작 변경(청산선 · 진입 조건)은 그대로 반영된다. **main 에는 실거래에 넣어도 되는 커밋만 push 한다.**
- **장중 즉시 반영**이 필요하면 직접 재시작한다: `sudo systemctl restart stock-trade`(같은 게이트를 거친다). `./stop.sh && ./start.sh` 는 쓰지 않는다 — systemd 밖 프로세스가 생기고 게이트도 건너뛴다. 수동 재시작은 부팅 직후가 아니므로 휴장일 자동 종료가 걸리지 않는다.
- 서버에서 직접 파일을 고치면(커밋 안 된 수정) 그날부터 자동 반영이 멈춘다(`[update FAILED]`). 서버에서는 고치지 않는다.

### 2. 알림 채널

`.env` 에 설정된 채널로만 보낸다. 둘 다 설정하면 둘 다 보낸다.

#### 이메일 (Amazon SNS, 운영 기본)

서버에 비밀값이 없다. 서버는 인스턴스 역할 자격 증명으로 publish 하고, 그 역할에는 이 topic 하나에 대한 `sns:Publish` 만 허용한다. 서버의 AL2023 기본 AWS CLI 로 보내므로 boto3 가 필요 없다. 메일 제목에 주소가 들어가서(`StockTrader up 10-19 08:21 http://x.x.x.x:8501`) 알림 미리보기만으로 IP 가 보인다. 요금은 월 1,000건까지 무료다.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
TOPIC=$(aws sns create-topic --name stock-trade-alerts --attributes DisplayName=StockTrader --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC" --protocol email --notification-endpoint <받을 주소>   # 확인 메일의 링크를 클릭
aws iam put-role-policy --role-name stock-trade-ec2-ssm --policy-name sns-publish-alerts \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sns:Publish\",\"Resource\":\"$TOPIC\"}]}"
```

서버 `.env` 에 `NOTIFY_SNS_TOPIC_ARN=<TOPIC>` 을 넣는다. 구독 확인을 하기 전에 보낸 메시지는 버려진다.

#### 텔레그램 (선택)

1. 텔레그램에서 `@BotFather` → `/newbot` → 토큰을 받는다.
2. 만든 봇에게 아무 메시지나 한 번 보낸 뒤, `https://api.telegram.org/bot<토큰>/getUpdates` 를 열어 `"chat":{"id": ...}` 값을 확인한다.
3. 서버의 `.env` 에 추가한다.

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```

4. 시험 발송: `.venv/bin/python -m scripts.boot_notify` 를 실행하면 `🟢 트레이더 기동 ...` 이 온다. 가동한 지 10분이 지났으면 휴장일이어도 서버를 끄지 않는다. `--dry-run` 을 붙이면 보내지 않고 출력만 한다.

### 3. 스케줄러 (로컬 또는 CloudShell 에서, AWS CLI)

스케줄러가 EC2 를 켜고 끌 수 있게 하는 Role 이다. 권한은 이 인스턴스 하나로 좁힌다.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-northeast-2
INSTANCE_ID=i-xxxxxxxxxxxxxxxxx

aws iam create-role --role-name stock-trade-scheduler \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"scheduler.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name stock-trade-scheduler --policy-name ec2-start-stop \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{\"Effect\":\"Allow\",
      \"Action\":[\"ec2:StartInstances\",\"ec2:StopInstances\"],
      \"Resource\":\"arn:aws:ec2:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}\"}]}"

for KIND in start stop; do
  if [ "$KIND" = start ]; then CRON="cron(20 8 ? * MON-FRI *)"; API=startInstances
  else CRON="cron(40 15 ? * MON-FRI *)"; API=stopInstances; fi
  aws scheduler create-schedule --region "$REGION" --name "stock-trade-$KIND" \
    --schedule-expression "$CRON" --schedule-expression-timezone Asia/Seoul \
    --flexible-time-window Mode=OFF \
    --target "{\"Arn\":\"arn:aws:scheduler:::aws-sdk:ec2:${API}\",
               \"RoleArn\":\"arn:aws:iam::${ACCOUNT_ID}:role/stock-trade-scheduler\",
               \"Input\":\"{\\\"InstanceIds\\\":[\\\"${INSTANCE_ID}\\\"]}\"}"
done
```

Role 을 만든 직후에는 IAM 전파에 몇 초가 걸려 `create-schedule` 이 실패할 수 있다. 그러면 다시 실행하면 된다.

### 4. 대시보드 접근 제한 (권장)

대시보드에는 인증이 없고, 사이드바에서 운영 설정을 바꿀 수 있다. IP 가 매일 바뀌어도 포트 스캐너는 금방 찾아낸다.

- **최소한**: Security Group 의 8501 inbound 를 내 IP 로 제한한다.
- **더 나은 대안**: Tailscale(개인 무료)을 쓰면 inbound 포트를 전부 닫고도 `http://<호스트명>:8501` 처럼 고정된 이름으로 들어갈 수 있다. 그러면 IP 변경 문제 자체가 사라지고, 텔레그램 알림은 heartbeat 용도로만 남는다. KIS 호출에는 outbound 인터넷이 필요하므로 public IP 는 그대로 둔다.

## 운영 중 확인

현재 주소는 로컬에서 바로 확인할 수 있다(텔레그램이 없어도 된다).

```bash
AWS_PROFILE=stock-trade AWS_REGION=ap-northeast-2 aws ec2 describe-instances \
  --instance-ids i-07063559d4c6bb3b2 \
  --query 'Reservations[0].Instances[0].[State.Name,PublicIpAddress]' --output text
```

서버 명령은 SSH 대신 SSM Run Command 로도 실행할 수 있다. 인스턴스 역할 `stock-trade-ec2-ssm`(`AmazonSSMManagedInstanceCore`)이 붙어 있다.

```bash
AWS_PROFILE=stock-trade AWS_REGION=ap-northeast-2 aws ssm send-command \
  --instance-ids i-07063559d4c6bb3b2 --document-name AWS-RunShellScript \
  --parameters 'commands=["systemctl restart stock-trade"]'   # 장중 즉시 반영 — 재시작이 검증 게이트를 거쳐 갱신한다
```

| 상황 | 할 일 |
|---|---|
| 08:25 까지 알림이 없다 | 스케줄러 실패이거나 부팅 실패. 콘솔에서 인스턴스 상태와 `aws scheduler get-schedule --name stock-trade-start` 를 확인한다 |
| `🔴 트레이더 기동 실패` | `logs/startup.log`, `journalctl -u stock-trade -b` |
| 휴일에 점검하려고 직접 켰다 | 알림을 받은 뒤 5분 안에 `sudo shutdown -c` 로 취소한다. 오래 작업할 거면 `touch ~/codes/stock_trade/.stay_up` 을 해 두고, 끝나면 지운다 |
| 오늘은 장중에 서버를 계속 켜 두고 싶다 | 아무것도 안 해도 된다. 15:40 스케줄러가 끈다 |
| 15:40 이후에도 켜 두고 싶다 | 콘솔에서 `stock-trade-stop` 스케줄을 잠시 Disable 한다 |

## 비용 (서울 리전, 대략)

평일 약 7.3시간 × 월 21일 ≈ 155시간 기준이다.

- **t3.micro**: 약 $2. 상시 가동이면 약 $9.5.
- **public IPv4**: 시간당 $0.005 이고 켜진 시간에만 붙어 약 $0.8. Elastic IP 는 꺼져 있어도 과금되어 월 $3.6 고정이다.
- **EBS 8GB**: 약 $0.7. 꺼져 있어도 과금된다.
- **EventBridge Scheduler**: 월 1,400만 건까지 무료.

합계는 월 약 $3.5 이다(상시 가동 + Elastic IP 는 약 $14). 정확한 단가는 AWS 요금 페이지에서 확인할 것.
