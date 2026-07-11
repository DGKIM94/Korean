// ===================== korean2_no_relay_dual_device_18ch_softpwm.ino =====================
// Arduino Due / 18 motors / relay removed
//
// Device 1 (@): motor 1~9 -> pins 37,39,41,43,45,47,49,51,53
// Device 2 (#): motor 1~9 -> pins 38,36,34,32,30,28,26,24,22
//
// NOTE:
// - Arduino Due hardware PWM pins are mainly 2~13, not 22~53.
// - This sketch therefore uses SOFTWARE PWM so pins 22~53 can still use 0~255 intensity.
// - If you only need ON/OFF, values 0 or 255 behave as simple digital LOW/HIGH.
//
// Serial: 115200 baud, end command with LF or ';'
//
// Basic syntax
//   @1/300              : Device 1 motor 1, 255 strength, 300 ms
//   #2=120/300          : Device 2 motor 2, strength 120, 300 ms
//   @1,2/300            : Device 1 motors 1+2 simultaneously, 300 ms
//   #1=80,2=200/300     : Device 2 motor 1=80, motor 2=200, 300 ms
//   @1/1000/i           : Device 1 motor 1 ramp up for 1000 ms
//   #3/1000/d           : Device 2 motor 3 ramp down for 1000 ms
//   @1/i,3/d/300        : Device 1 motor 1 ramp up + motor 3 ramp down, 300 ms
//   @0                  : all motors OFF
//
// Sequential using dot
//   @1/200.0/100.#2/200
//      Device 1 motor 1 200 ms -> rest 100 ms -> Device 2 motor 2 200 ms
//
// Cross-device simultaneous in the same step: put @ and # in the SAME dot section
//   @1/300#2/300
//      Device 1 motor 1 and Device 2 motor 2 start together for 300 ms
//   @1=100/500#1=200/500.0/100.@2/300#2/300
//      both devices together -> rest -> both devices together
//
// Important hardware:
//   motor + -> external 3.0~3.3V motor supply +
//   motor - -> NPN collector
//   NPN emitter -> GND
//   Due pin -> 680R~1k -> NPN base
//   motor supply GND == Arduino GND
// ============================================================================

#include <Arduino.h>
#include <math.h>

#define ENABLE_LOG 0

// ===================== settings =====================
const uint8_t DEV_CH = 9;
const uint8_t NCH = 18;

// index 1..18, 0 dummy
// global channel 1~9   = device 1 motor 1~9
// global channel 10~18 = device 2 motor 1~9
const uint8_t pinMap[19] = {
  0,
  37,39,41,43,45,47,49,51,53,
  38,36,34,32,30,28,26,24,22
};

const uint8_t MAX_EVENTS = 160;
const uint16_t STEP_MS = 5;

// software PWM period. 1000 us = 1 kHz.
// Raise to 2000 for lighter CPU / lower pitch, lower to 500 for higher pitch.
const uint16_t SW_PWM_PERIOD_US = 1000;

const float RAMP_GAMMA_UP   = 1.0f;
const float RAMP_GAMMA_DOWN = 1.0f;

// ===================== types =====================
enum TailOpt : uint8_t { OPT_NONE=0, OPT_I, OPT_D };
enum EnvMode : uint8_t { ENV_OFF=0, ENV_FIXED, ENV_RAMP_UP, ENV_RAMP_DOWN };
enum EKind : uint8_t { EK_START_FIXED, EK_START_RAMP_UP, EK_START_RAMP_DOWN, EK_OFF };

struct ChannelEnv {
  EnvMode mode = ENV_OFF;
  unsigned long t0 = 0;
  unsigned long dur = 0;
  uint8_t fixedVal = 0;
  bool active = false;
  unsigned long lastStep = 0;
  uint8_t lastOut = 0;
  uint16_t stepIdx = 0;
  uint16_t stepMax = 0;
};

struct Event {
  unsigned long at;
  uint32_t mask;
  EKind kind;
  unsigned long dur;
  uint8_t val;
  bool usePerVal;
  uint8_t perVal[19];
  bool usePerMode;
  EnvMode perMode[19];
  bool active;
};

ChannelEnv chEnv[19];
Event evts[MAX_EVENTS];
uint8_t desiredOut[19];
bool pinState[19];

// ===================== small utils =====================
void logPrefix(){
#if ENABLE_LOG
  Serial.print('['); Serial.print(millis()); Serial.print(F(" ms] "));
#endif
}

static inline uint8_t localToGlobal(uint8_t dev, uint8_t localCh){
  // dev 1 => 1..9, dev 2 => 10..18
  return (dev == 1) ? localCh : (uint8_t)(9 + localCh);
}

bool isDigitStr(const String& s){
  if (s.length()==0) return false;
  for (uint16_t i=0;i<s.length(); i++) if (!isDigit(s[i])) return false;
  return true;
}

static inline int countChar(const String& s, char target){
  int cnt = 0;
  for (int i=0; i<(int)s.length(); i++) if (s[i] == target) cnt++;
  return cnt;
}

TailOpt parseTailOpt(const String& s){
  String t=s; t.trim(); t.toLowerCase();
  if (t=="i") return OPT_I;
  if (t=="d") return OPT_D;
  return OPT_NONE;
}

static inline uint8_t rampPow01(float x, float gamma){
  if (x < 0) x = 0;
  if (x > 1) x = 1;
  float y = powf(x, gamma);
  int v = (int)lroundf(255.0f * y);
  return (uint8_t)constrain(v, 0, 255);
}

uint32_t allChannelMask(){
  uint32_t mask = 0;
  for (uint8_t ch=1; ch<=NCH; ch++) mask |= (1UL << ch);
  return mask;
}

// ===================== software PWM =====================
void motorSet(uint8_t ch, uint8_t out){
  if (ch < 1 || ch > NCH) return;
  desiredOut[ch] = out;

  // force stable states immediately for 0 and 255
  if (out == 0){
    digitalWrite(pinMap[ch], LOW);
    pinState[ch] = false;
  } else if (out == 255){
    digitalWrite(pinMap[ch], HIGH);
    pinState[ch] = true;
  }
}

void serviceSoftwarePWM(){
  static uint32_t lastPeriodStart = 0;
  uint32_t now = micros();

  if ((uint32_t)(now - lastPeriodStart) >= SW_PWM_PERIOD_US){
    lastPeriodStart += SW_PWM_PERIOD_US;
    // recover if loop was delayed too long
    if ((uint32_t)(now - lastPeriodStart) >= SW_PWM_PERIOD_US) lastPeriodStart = now;

    for (uint8_t ch=1; ch<=NCH; ch++){
      uint8_t out = desiredOut[ch];
      if (out == 0){
        if (pinState[ch]) { digitalWrite(pinMap[ch], LOW); pinState[ch]=false; }
      } else if (out == 255){
        if (!pinState[ch]) { digitalWrite(pinMap[ch], HIGH); pinState[ch]=true; }
      } else {
        if (!pinState[ch]) { digitalWrite(pinMap[ch], HIGH); pinState[ch]=true; }
      }
    }
  }

  uint16_t phase = (uint16_t)((uint32_t)(now - lastPeriodStart));
  for (uint8_t ch=1; ch<=NCH; ch++){
    uint8_t out = desiredOut[ch];
    if (out == 0 || out == 255) continue;

    uint16_t onTime = ((uint32_t)out * SW_PWM_PERIOD_US) / 255UL;
    bool shouldHigh = (phase < onTime);
    if (shouldHigh != pinState[ch]){
      digitalWrite(pinMap[ch], shouldHigh ? HIGH : LOW);
      pinState[ch] = shouldHigh;
    }
  }
}

// ===================== envelopes =====================
void envStart(uint8_t ch, EnvMode mode, unsigned long dur, uint8_t val=255){
  ChannelEnv &e = chEnv[ch];
  e.mode = mode;
  e.t0 = millis();
  e.dur = dur;
  e.fixedVal = val;
  e.active = true;
  e.lastStep = millis();
  e.stepIdx = 0;

  if (mode == ENV_RAMP_UP || mode == ENV_RAMP_DOWN){
    uint16_t n = (STEP_MS ? (dur + STEP_MS - 1) / STEP_MS : dur);
    if (n < 1) n = 1;
    e.stepMax = n;
  } else {
    e.stepMax = 0;
  }

  if (mode == ENV_RAMP_UP){
    motorSet(ch, 0);
    e.lastOut = 0;
  } else if (mode == ENV_RAMP_DOWN){
    motorSet(ch, 255);
    e.lastOut = 255;
  } else {
    motorSet(ch, val);
    e.lastOut = val;
  }
}

void envStop(uint8_t ch){
  if (ch < 1 || ch > NCH) return;
  ChannelEnv &e = chEnv[ch];
  e.active = false;
  e.mode = ENV_OFF;
  e.lastOut = 0;
  motorSet(ch, 0);
}

void stopAllChannelsNow(){
  for (uint8_t ch=1; ch<=NCH; ch++) envStop(ch);
}

void serviceEnvelopes(){
  unsigned long now = millis();
  for (uint8_t ch=1; ch<=NCH; ch++){
    ChannelEnv &e = chEnv[ch];
    if (!e.active) continue;
    if (STEP_MS && (now - e.lastStep) < STEP_MS) continue;
    e.lastStep = now;

    uint8_t out = 0;
    switch (e.mode){
      case ENV_FIXED:
        out = e.fixedVal;
        break;
      case ENV_RAMP_UP: {
        if (e.stepIdx >= e.stepMax) out = 255;
        else {
          float x = (e.stepMax<=1) ? 1.0f : (float)e.stepIdx / (float)(e.stepMax-1);
          out = rampPow01(x, RAMP_GAMMA_UP);
          e.stepIdx++;
        }
        break;
      }
      case ENV_RAMP_DOWN: {
        if (e.stepIdx >= e.stepMax) out = 0;
        else {
          float x = (e.stepMax<=1) ? 1.0f : (float)e.stepIdx / (float)(e.stepMax-1);
          out = 255 - rampPow01(x, RAMP_GAMMA_DOWN);
          e.stepIdx++;
        }
        break;
      }
      default:
        out = 0;
        break;
    }

    if (out != e.lastOut){
      e.lastOut = out;
      motorSet(ch, out);
    }
  }
}

// ===================== event queue =====================
void clearEvents(){
  for (uint8_t i=0; i<MAX_EVENTS; i++){
    evts[i].active = false;
    evts[i].usePerVal = false;
    evts[i].usePerMode = false;
    for (uint8_t k=0; k<19; k++){
      evts[i].perVal[k] = 0;
      evts[i].perMode[k] = ENV_OFF;
    }
  }
}

bool addEvent(unsigned long at, uint32_t mask, EKind kind, unsigned long dur=0, uint8_t val=255){
  for (uint8_t i=0; i<MAX_EVENTS; i++){
    if (!evts[i].active){
      evts[i].at = at;
      evts[i].mask = mask;
      evts[i].kind = kind;
      evts[i].dur = dur;
      evts[i].val = val;
      evts[i].usePerVal = false;
      evts[i].usePerMode = false;
      for (uint8_t k=0; k<19; k++){
        evts[i].perVal[k] = 0;
        evts[i].perMode[k] = ENV_OFF;
      }
      evts[i].active = true;
      return true;
    }
  }
  Serial.println(F("ERR: event queue full"));
  return false;
}

bool addEventPerVal(unsigned long at, uint32_t mask, unsigned long dur, const uint8_t perVal[19]){
  for (uint8_t i=0; i<MAX_EVENTS; i++){
    if (!evts[i].active){
      evts[i].at = at;
      evts[i].mask = mask;
      evts[i].kind = EK_START_FIXED;
      evts[i].dur = dur;
      evts[i].val = 255;
      evts[i].usePerVal = true;
      evts[i].usePerMode = false;
      for (uint8_t k=0; k<19; k++){
        evts[i].perVal[k] = perVal[k];
        evts[i].perMode[k] = ENV_OFF;
      }
      evts[i].active = true;
      return true;
    }
  }
  Serial.println(F("ERR: event queue full"));
  return false;
}

bool addEventPerMode(unsigned long at, uint32_t mask, unsigned long dur, const EnvMode perMode[19]){
  for (uint8_t i=0; i<MAX_EVENTS; i++){
    if (!evts[i].active){
      evts[i].at = at;
      evts[i].mask = mask;
      evts[i].kind = EK_START_FIXED;
      evts[i].dur = dur;
      evts[i].val = 255;
      evts[i].usePerVal = false;
      evts[i].usePerMode = true;
      for (uint8_t k=0; k<19; k++){
        evts[i].perVal[k] = 0;
        evts[i].perMode[k] = perMode[k];
      }
      evts[i].active = true;
      return true;
    }
  }
  Serial.println(F("ERR: event queue full"));
  return false;
}

void runDueEvents(){
  unsigned long now = millis();
  for (uint8_t i=0; i<MAX_EVENTS; i++){
    if (!evts[i].active) continue;
    if ((long)(now - evts[i].at) < 0) continue;

    for (uint8_t ch=1; ch<=NCH; ch++){
      if (!(evts[i].mask & (1UL << ch))) continue;

      if (evts[i].usePerMode){
        switch (evts[i].perMode[ch]){
          case ENV_FIXED:     envStart(ch, ENV_FIXED, evts[i].dur, 255); break;
          case ENV_RAMP_UP:   envStart(ch, ENV_RAMP_UP, evts[i].dur, 255); break;
          case ENV_RAMP_DOWN: envStart(ch, ENV_RAMP_DOWN, evts[i].dur, 255); break;
          default: break;
        }
        continue;
      }

      switch (evts[i].kind){
        case EK_START_FIXED:
          envStart(ch, ENV_FIXED, evts[i].dur, evts[i].usePerVal ? evts[i].perVal[ch] : evts[i].val);
          break;
        case EK_START_RAMP_UP:
          envStart(ch, ENV_RAMP_UP, evts[i].dur, 255);
          break;
        case EK_START_RAMP_DOWN:
          envStart(ch, ENV_RAMP_DOWN, evts[i].dur, 255);
          break;
        case EK_OFF:
          envStop(ch);
          break;
      }
    }
    evts[i].active = false;
  }
}

// ===================== parsers =====================
bool parseChListToMask(const String& s, uint8_t dev, uint32_t &mask){
  mask = 0;
  int pos = 0;
  while (pos < (int)s.length()){
    int c = s.indexOf(',', pos);
    String tok = (c==-1) ? s.substring(pos) : s.substring(pos,c);
    tok.trim();
    if (!isDigitStr(tok)) return false;
    int local = tok.toInt();
    if (local < 1 || local > 9) return false;
    uint8_t g = localToGlobal(dev, (uint8_t)local);
    mask |= (1UL << g);
    if (c==-1) break;
    pos = c + 1;
  }
  return (mask != 0);
}

bool parseChValListToMaskAndVals(const String& s, uint8_t dev, uint32_t &mask, uint8_t perVal[19]){
  mask = 0;
  for (uint8_t i=0; i<19; i++) perVal[i] = 0;

  int pos = 0;
  while (pos < (int)s.length()){
    int c = s.indexOf(',', pos);
    String tok = (c==-1) ? s.substring(pos) : s.substring(pos,c);
    tok.trim();
    if (tok.length()==0) return false;

    int eq = tok.indexOf('=');
    if (eq==-1) return false;

    String chStr = tok.substring(0,eq); chStr.trim();
    String vStr  = tok.substring(eq+1); vStr.trim();
    if (!isDigitStr(chStr)) return false;

    int local = chStr.toInt();
    if (local < 1 || local > 9) return false;
    int vv = constrain(vStr.toInt(), 0, 255);

    uint8_t g = localToGlobal(dev, (uint8_t)local);
    mask |= (1UL << g);
    perVal[g] = (uint8_t)vv;

    if (c==-1) break;
    pos = c + 1;
  }
  return (mask != 0);
}

bool parseChModeList(const String& s, uint8_t dev, uint32_t &mask, EnvMode perMode[19]){
  mask = 0;
  for (uint8_t i=0; i<19; i++) perMode[i] = ENV_OFF;

  int pos = 0;
  while (pos < (int)s.length()){
    int c = s.indexOf(',', pos);
    String tok = (c==-1) ? s.substring(pos) : s.substring(pos,c);
    tok.trim();
    if (tok.length()==0) return false;

    int slash = tok.indexOf('/');
    if (slash==-1) return false;

    String chStr = tok.substring(0,slash); chStr.trim();
    String modeStr = tok.substring(slash+1); modeStr.trim(); modeStr.toLowerCase();
    if (!isDigitStr(chStr)) return false;

    int local = chStr.toInt();
    if (local < 1 || local > 9) return false;

    EnvMode mode = ENV_OFF;
    if (modeStr == "i") mode = ENV_RAMP_UP;
    else if (modeStr == "d") mode = ENV_RAMP_DOWN;
    else if (modeStr == "f") mode = ENV_FIXED;
    else return false;

    uint8_t g = localToGlobal(dev, (uint8_t)local);
    mask |= (1UL << g);
    perMode[g] = mode;

    if (c==-1) break;
    pos = c + 1;
  }
  return (mask != 0);
}

void printStatus(){
  Serial.println(F("STATUS:"));
  for (uint8_t ch=1; ch<=NCH; ch++){
    uint8_t dev = (ch <= 9) ? 1 : 2;
    uint8_t local = (ch <= 9) ? ch : (ch - 9);
    Serial.print(F("D")); Serial.print(dev);
    Serial.print(F(" CH")); Serial.print(local);
    Serial.print(F(" pin=")); Serial.print(pinMap[ch]);
    Serial.print(F(" out=")); Serial.print(desiredOut[ch]);
    Serial.print(F(" active=")); Serial.println(chEnv[ch].active ? F("Y") : F("N"));
  }
}

// Parse one command body for one device. Schedules at startAt. Returns consumed time.
// body examples: "1/300", "1=80/300", "1=80,2=200/300", "1/i,3/d/300", "0/100", "0", "?"
bool parseOneBodyAndSchedule(const String& bodyIn, uint8_t dev, unsigned long startAt, unsigned long &consumed){
  consumed = 0;
  String tok = bodyIn;
  tok.trim();
  if (tok.length()==0) return true;

  if (tok == "?"){
    printStatus();
    return true;
  }

  // all off now
  if (tok == "0"){
    addEvent(startAt, allChannelMask(), EK_OFF, 0, 0);
    return true;
  }

  // rest: 0/ms
  if (tok.startsWith("0/")){
    String msStr = tok.substring(2); msStr.trim();
    if (!isDigitStr(msStr)) { Serial.println(F("ERR: bad rest duration")); return false; }
    consumed = msStr.toInt();
    return true;
  }

  // channel-specific mode: 1/i,3/d/300
  {
    int lastSlash = tok.lastIndexOf('/');
    if (lastSlash != -1){
      String leftPart = tok.substring(0, lastSlash); leftPart.trim();
      String durPart  = tok.substring(lastSlash+1); durPart.trim();
      if (isDigitStr(durPart) &&
          (leftPart.indexOf("/i")!=-1 || leftPart.indexOf("/I")!=-1 ||
           leftPart.indexOf("/d")!=-1 || leftPart.indexOf("/D")!=-1 ||
           leftPart.indexOf("/f")!=-1 || leftPart.indexOf("/F")!=-1)){
        uint32_t mask; EnvMode perMode[19];
        if (parseChModeList(leftPart, dev, mask, perMode)){
          unsigned long ms = durPart.toInt();
          addEventPerMode(startAt, mask, ms, perMode);
          addEvent(startAt + ms, mask, EK_OFF, 0, 0);
          consumed = ms;
          return true;
        }
      }
    }
  }

  // fixed with '='
  if (tok.indexOf('=') != -1){
    int slashTok = tok.indexOf('/');
    String leftPart;
    String durPart = "";
    if (slashTok == -1) leftPart = tok;
    else { leftPart = tok.substring(0, slashTok); durPart = tok.substring(slashTok+1); }
    leftPart.trim(); durPart.trim();

    int eqCount = countChar(leftPart, '=');
    if (eqCount == 1){
      // "1,2=120"
      int eq = leftPart.indexOf('=');
      String chList = leftPart.substring(0,eq); chList.trim();
      String vStr   = leftPart.substring(eq+1); vStr.trim();
      uint32_t mask;
      if (!parseChListToMask(chList, dev, mask)) { Serial.println(F("ERR: bad ch list")); return false; }
      uint8_t val = (uint8_t)constrain(vStr.toInt(), 0, 255);
      addEvent(startAt, mask, EK_START_FIXED, 0, val);
      if (durPart.length()){
        if (!isDigitStr(durPart)) { Serial.println(F("ERR: bad duration")); return false; }
        unsigned long ms = durPart.toInt();
        addEvent(startAt + ms, mask, EK_OFF, 0, 0);
        consumed = ms;
      }
      return true;
    } else {
      // "1=80,2=200"
      uint32_t mask; uint8_t perVal[19];
      if (!parseChValListToMaskAndVals(leftPart, dev, mask, perVal)) { Serial.println(F("ERR: bad ch=val list")); return false; }
      addEventPerVal(startAt, mask, 0, perVal);
      if (durPart.length()){
        if (!isDigitStr(durPart)) { Serial.println(F("ERR: bad duration")); return false; }
        unsigned long ms = durPart.toInt();
        addEvent(startAt + ms, mask, EK_OFF, 0, 0);
        consumed = ms;
      }
      return true;
    }
  }

  // normal: chlist/ms[/i|d]
  int slash1 = tok.indexOf('/');
  if (slash1 == -1){
    Serial.println(F("ERR: token missing '/'"));
    return false;
  }
  String left = tok.substring(0, slash1); left.trim();
  String right = tok.substring(slash1+1); right.trim();

  int slash2 = right.indexOf('/');
  String msStr  = (slash2==-1) ? right : right.substring(0, slash2);
  String optStr = (slash2==-1) ? ""    : right.substring(slash2+1);
  msStr.trim(); optStr.trim();

  if (!isDigitStr(msStr)) { Serial.println(F("ERR: bad duration")); return false; }
  unsigned long ms = msStr.toInt();
  TailOpt opt = parseTailOpt(optStr);

  uint32_t mask;
  if (!parseChListToMask(left, dev, mask)) { Serial.println(F("ERR: bad ch list")); return false; }

  EKind k = EK_START_FIXED;
  if (opt == OPT_I) k = EK_START_RAMP_UP;
  else if (opt == OPT_D) k = EK_START_RAMP_DOWN;

  addEvent(startAt, mask, k, ms, 255);
  addEvent(startAt + ms, mask, EK_OFF, 0, 0);
  consumed = ms;
  return true;
}

// Parse dot-separated steps. Within one step, @ and # chunks start simultaneously.
bool parseScriptAndSchedule(const String& scriptIn){
  String s = scriptIn;
  s.trim();
  if (s.length()==0) return false;

  clearEvents();
  stopAllChannelsNow();

  unsigned long base = millis();
  unsigned long tOffset = 0;
  uint8_t currentDev = 1;
  bool haveDev = false;

  int pos = 0;
  while (pos <= (int)s.length()){
    int dot = s.indexOf('.', pos);
    String step = (dot == -1) ? s.substring(pos) : s.substring(pos, dot);
    step.trim();
    pos = (dot == -1) ? (int)s.length()+1 : dot+1;
    if (step.length()==0) continue;

    unsigned long stepMax = 0;
    int p = 0;

    // If step does not begin with @/#, use previous device marker.
    if (step[0] != '@' && step[0] != '#'){
      if (!haveDev) { Serial.println(F("ERR: script must start with @ or #")); return false; }
      unsigned long consumed = 0;
      if (!parseOneBodyAndSchedule(step, currentDev, base + tOffset, consumed)) return false;
      stepMax = consumed;
    } else {
      while (p < (int)step.length()){
        char marker = step[p];
        if (marker != '@' && marker != '#'){
          Serial.println(F("ERR: bad device marker"));
          return false;
        }
        currentDev = (marker == '@') ? 1 : 2;
        haveDev = true;
        p++;

        int next = p;
        while (next < (int)step.length() && step[next] != '@' && step[next] != '#') next++;
        String body = step.substring(p, next);
        body.trim();

        unsigned long consumed = 0;
        if (!parseOneBodyAndSchedule(body, currentDev, base + tOffset, consumed)) return false;
        if (consumed > stepMax) stepMax = consumed;

        p = next;
      }
    }

    tOffset += stepMax;
  }
  return true;
}

// ===================== serial =====================
char buf[300];
uint16_t blen = 0;
bool collecting = false;

void flushAndParse(){
  if (!(collecting && blen)){
    blen = 0; collecting = false;
    return;
  }

  String script;
  script.reserve(blen+4);
  for (uint16_t i=0; i<blen; i++) script += buf[i];

  bool ok = parseScriptAndSchedule(script);
  if (!ok) Serial.println(F("ERR: parse failed"));
  else Serial.println(F("OK"));

  blen = 0;
  collecting = false;
}

// ===================== setup/loop =====================
void setup(){
  Serial.begin(115200);

  for (uint8_t ch=1; ch<=NCH; ch++){
    pinMode(pinMap[ch], OUTPUT);
    digitalWrite(pinMap[ch], LOW);
    desiredOut[ch] = 0;
    pinState[ch] = false;
    chEnv[ch].active = false;
    chEnv[ch].mode = ENV_OFF;
    chEnv[ch].lastOut = 0;
  }

  clearEvents();
  Serial.println(F("READY dual-device no-relay soft-PWM"));
}

void loop(){
  while (Serial.available()){
    char c = (char)Serial.read();

    if (c=='@' || c=='#'){
      if (!collecting){ blen = 0; collecting = true; }
      if (blen < sizeof(buf)-1) buf[blen++] = c;
      continue;
    }

    if (!collecting) continue;

    if (c=='\n' || c=='\r' || c==';'){
      flushAndParse();
      continue;
    }

    if (c==' ' || c=='\t') continue;

    if (isdigit(c) || c==',' || c=='/' || c=='.' || c=='=' ||
        c=='i' || c=='d' || c=='f' || c=='I' || c=='D' || c=='F' || c=='?'){
      if (blen < sizeof(buf)-1) buf[blen++] = c;
    }
  }

  runDueEvents();
  serviceEnvelopes();
  serviceSoftwarePWM();
}
