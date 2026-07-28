from DrissionPage import Chromium, ChromiumOptions
import time
import random
import csv
import os

tabPort = 2727
dp=Chromium(tabPort)
tab=dp.get_tab()

# tab.ele("@class=sdf",timeout=0.1).click()

def seeMoreClick(ele):
    try:
        btns=ele.eles("@class=x1i10hfl xjbqb8w x1ejq31n x18oe1m7 x1sy0etr xstzfhl x972fbf x10w94by x1qhh985 x14e42zd x9f619 x1ypdohk xt0psk2 x3ct3a4 xdj266r x14z9mp xat24cr x1lziwak xexx8yu xyri2b x18d9i69 x1c1uobl x16tdsg8 x1hl2dhg xggy1nq x1a2a7pz xkrqix3 x1sur9pj xzsf02u x1s688f",timeout=1)
        for btnItem in btns:
            if 'See more' in btnItem.text:
                btnItem.click(by_js=True)
                return True
        return False
    except Exception as e:
        return False


targetDiv=None
divEles=tab.eles("@class=x1yztbdb",timeout=1)
for divEleItem in divEles:
    if 'Posts' in divEleItem.text:
        targetDiv=divEleItem
        break

if not targetDiv:
    print("未找到 Posts 相关的元素")
    exit()

CSV_PATH = r"c:\Users\86150\Desktop\facebook280\data.csv"

seenIndices = set()  # 本轮已采集的帖子索引，用于去重
while True:
    postEles=targetDiv.next().children()
    for postItem in postEles:
        try:
            eleIndex=''
            fbz=''
            zw=''
            sj=''
            postUrl=''
            dz=''
            yData=''

            # div索引
            divs=postItem.eles("@@tag()=div@@class=x1a2a7pz",timeout=1)
            for divItem in divs:
                if divItem.attr('aria-posinset')!=None:
                    eleIndex=divItem.attr('aria-posinset')
                    break

            # 去重判断（按 eleIndex）
            if eleIndex and eleIndex in seenIndices:
                print(f'跳过索引: {eleIndex}')
                continue
            seenIndices.add(eleIndex)
            postItem.scroll.to_see()

            # 获取链接
            sjEle=postItem.ele("@class=x1i10hfl xjbqb8w x1ejq31n x18oe1m7 x1sy0etr xstzfhl x972fbf x10w94by x1qhh985 x14e42zd x9f619 x1ypdohk xt0psk2 x3ct3a4 xdj266r x14z9mp xat24cr x1lziwak xexx8yu xyri2b x18d9i69 x1c1uobl x16tdsg8 x1hl2dhg xggy1nq x1a2a7pz xkrqix3 x1sur9pj xi81zsa x1s688f",timeout=1)
            if sjEle:
                postUrl=sjEle.link

            # 发布时间
            sjEle.hover()
            time.sleep(random.uniform(1,2))
            sjNr=tab.ele("@class=x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1nxh6w3 x1sibtaa xo1l8bm xzsf02u",timeout=3)
            if sjNr:
                sj=sjNr.text
            print(sj)

            # 正文
            zwEle=postItem.ele("@class=xdj266r x14z9mp xat24cr x1lziwak x1vvkbs x126k92a",timeout=1)
            if zwEle:
                zwEle.hover()
                seeMoreClick(zwEle)
                time.sleep(random.uniform(1,2))
                zw=zwEle.text
                zw=zw.removesuffix('See less').strip()
            # print(zw)


            # 发布者名称
            fbzEle=postItem.ele("@class=html-span xdj266r x14z9mp xat24cr x1lziwak xexx8yu xyri2b x18d9i69 x1c1uobl x1hl2dhg x16tdsg8 x1vvkbs",timeout=1)
            if fbzEle:
                fbz=fbzEle.text
            # print(fbz)

            # 点赞数
            dzEle=postItem.ele("@class=xj87blo x6ikm8r x10wlt62 xlyipyv x1exxlbk",timeout=1)
            if dzEle:
                dz=dzEle.text
            # print(dz)

            # 右边数据
            yDataEle=postItem.ele("@class=x9f619 x1ja2u2z x78zum5 x2lah0s x1n2onr6 x1qughib x1qjc9v5 xozqiw3 x1q0g3np xyri2b x1c1uobl x1ws5yxj xw01apr x4cne27 xifccgj x123j3cw xs9asl8",timeout=1)
            if yDataEle:
                yData=yDataEle.text
                yData=yData.replace('\n', ' ').strip()
            # print(yData)
            
            # 即刻写入 CSV
            file_exists = os.path.exists(CSV_PATH)
            with open(CSV_PATH, 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['发布者', '发布时间', '正文内容', '点赞数', '右边数据', '链接'])
                writer.writerow([fbz, sj, zw, dz, yData, postUrl])
            print(f"已写入: [{eleIndex}] {sj}")
        except Exception as e:
            input(e)
            pass
    tab.scroll(100)
            
