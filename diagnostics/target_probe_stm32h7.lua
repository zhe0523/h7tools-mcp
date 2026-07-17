print("H7TOOL_TARGET_BEGIN")
local A=0x1FF1E800
local L=12
local function hx(b)
  local s=""
  if b==nil then return s end
  for i=1,#b do s=s..string.format("%02X ",string.byte(b,i)) end
  return s
end
local function p32(k,v)
  local n=tonumber(v)
  if n then print(string.format("%s=0x%08X",k,n)) else print(k.."=unavailable") end
end
if pg_init then
  local r=pg_init()
  if r==nil then print("pg_init=nil") else print("pg_init="..r) end
else print("pg_init=unavailable") end
if pg_swd then
  local r=pg_swd("JTAG2SWD")
  if r==nil then print("jtag2swd=nil") else print("jtag2swd="..r) end
end
if pg_detect_ic then p32("idcode",pg_detect_ic()) else print("idcode=unavailable") end
print(string.format("uid_address=0x%08X",A))
print(string.format("uid_length=%d",L))
if pg_read_mem then
  local r,u=pg_read_mem(A,L)
  print("uid_read="..tostring(r))
  if r==1 and u then print("uid="..hx(u)) end
else
  print("uid_read=unavailable")
end
print("H7TOOL_TARGET_END")
