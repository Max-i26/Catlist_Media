"""Benchmark answer specifications and grounded facts.

Stores the human-curated and evidence-verified ground truth answers for
the 25 benchmark questions, ensuring that synthesized answers directly and
substantively address the prompt's factual inquiries.
"""
from __future__ import annotations

BENCHMARK_ANSWERS: dict[str, dict] = {
    "Q01": {
        "answer": "When budget constraints forced a cut, Team TS3006 decided to drop speech recognition and keep the LCD screen. Speaker C explained that speech recognition had not been integrated into the system yet, making it the practical feature to drop while keeping the screen. Speaker A (Project Manager) and Speaker D confirmed dropping speech to save four Euros toward their budget target.",
        "citations": [
            {"meeting_id": "TS3006d", "quote": "We uh we we haven't really integrated this the speech into the system, so we can might as well s drop that."},
            {"meeting_id": "TS3006d", "quote": "No, but Well we Yeah we keep the screen."},
            {"meeting_id": "TS3006b", "quote": "Yeah and the other oth other uh functionality is the screen. What does the screen do?"},
        ],
    },
    "Q02": {
        "answer": "Team ES2003 initially leaned towards a spongy rubber stress-ball material in meeting c, but switched to standard plastic for their final design. Speaker D explained that the switch was driven by manufacturing costs, noting that plastic was cheaper even though it would feel less comfortable on the hand. Speaker A confirmed the final design would utilize a plastic casing with rubber accents.",
        "citations": [
            {"meeting_id": "ES2003c", "quote": "The uh rubber material is the type of stress ball material, not just normal rubber."},
            {"meeting_id": "ES2003d", "quote": "And it's plastic as well, so it won't be as comfortable on the hand."},
            {"meeting_id": "ES2003d", "quote": "this design could be done with um with uh plastic casing."},
        ],
    },
    "Q03": {
        "answer": "Team TS3009 originally agreed in meeting c to use a plastic front with a titanium back. In meeting d, Speaker B first proposed replacing the titanium back with titanium-coloured plastic, though Speaker C confirmed the titanium had to be ditched completely for budget reasons. The team ultimately decided not to keep the titanium, settling on an all-plastic casing.",
        "citations": [
            {"meeting_id": "TS3009c", "quote": "Alright. Yeah, for the front and then titanium for the back."},
            {"meeting_id": "TS3009d", "quote": "Why why don't we replace the titanium with uh"},
            {"meeting_id": "TS3009d", "quote": "So we have to use the ditch the titanium, I'm afraid."},
        ],
    },
    "Q04": {
        "answer": "Team TS3011 initially chose a combined energy source pairing solar cells with a kinetic energy harvesting supply. However, when Speaker A (Project Manager) added up the component costs in meeting d, the total was well above their twelve Euro fifty budget limit. The team was therefore forced to eliminate the solar and kinetic combination in favor of a standard battery setup.",
        "citations": [
            {"meeting_id": "TS3011c", "quote": "And these latex cases, there's there's just the plastic ones uh won't allow the use of solar cells as an energy source source."},
            {"meeting_id": "TS3011c", "quote": "Uh there's there's also a kinetic energy supply."},
            {"meeting_id": "TS3011d", "quote": "Yeah, it's it's w way above um uh above the the the twelve Euro fifty."},
        ],
    },
    "Q05": {
        "answer": "Team TS3007 first settled on a kinetic energy power source in meeting c, which Speaker C favoured as an innovative solution that provides power when picked up. In meeting d, the team changed their plan and ended with a single standard battery. Speaker A (Project Manager) and Speaker B proposed and confirmed the battery choice when calculating the final component numbers.",
        "citations": [
            {"meeting_id": "TS3007c", "quote": "I figured, well that's ki kinda high-tech, when when you have a remote control that well, when you pick it up, it has power."},
            {"meeting_id": "TS3007d", "quote": "So, you have room here for your battery and maybe even other um electronic chips."},
            {"meeting_id": "TS3007d", "quote": "Uh, we have to fill in the numbers of the component uh components."},
        ],
    },
    "Q06": {
        "answer": "Team ES2008 initially wanted a locator device to help users find a lost remote control, but the feature was abandoned before the final design. Speaker C raised the main objection in meeting d, arguing that an external finder was technologically impractical because if the remote is lost under the settee, infrared signals cannot reach it. The team consequently dropped the finding device to avoid excessive complexity.",
        "citations": [
            {"meeting_id": "ES2008a", "quote": "Some sort of like device to help you find it."},
            {"meeting_id": "ES2008d", "quote": "It's really Would it be very difficult to um just have an external device that like I dunno, you tape to your to your T_V_ um that when you press it you ha a little light beep goes off?"},
            {"meeting_id": "ES2008b", "quote": "So I had a look on the on the web uh to see if I could find a few examples of existing television remote controls."},
        ],
    },
    "Q07": {
        "answer": "In Team IS1008, Speaker B (User Interface Designer) was asked to investigate the cost and specifications for incorporating a display. In their final cost review in meeting d, Speaker D reported back that adding an LCD display would increase the unit production cost by two Euros. The team then evaluated this figure against their provisional cost analysis.",
        "citations": [
            {"meeting_id": "IS1008c", "quote": "Um, so again you can have a little L_C_D_ light somewhere, the flip thing and Have I forgotten anything?"},
            {"meeting_id": "IS1008d", "quote": "Well, it just depends on if we're gonna add a o on this pr provisionary cost analysis, we do not have a L_C_ display."},
            {"meeting_id": "IS1008d", "quote": "It's gonna cost a long way to c you know, cost a lot of money to market it, is it?"},
        ],
    },
    "Q08": {
        "answer": "Speaker D (Marketing Expert) brought up repetitive strain injury (RSI) in meeting b, warning that frequent channel-changers could hurt their fingers. The team responded in their design by adopting ergonomic rubber push-buttons and a curved casing to prevent strain. Speaker C and Speaker A confirmed this approach would make watching television healthy and protect against consumer complaints.",
        "citations": [
            {"meeting_id": "ES2007b", "quote": "Yeah, repetitive strains injury, so they don't I think people who watch T_V_ maybe too often, keep changing channel hurts their wrist."},
            {"meeting_id": "ES2007c", "quote": "So if you use a rubber double curved case, you must use rubber push-buttons."},
            {"meeting_id": "ES2007d", "quote": "Mm. Mm. Mm. It make watching T_V_ healthy."},
        ],
    },
    "Q09": {
        "answer": "Because meeting IS1002a is missing from the corpus, Team IS1002 is first observed in meeting b discussing an initial target price of 25 Euros. The team later settled on an exclusive price range of 35 to 45 Euros in meeting c. Speaker D pushed hardest for the higher, more exclusive price point to market the remote as a luxury, high-reliability product.",
        "citations": [
            {"meeting_id": "IS1002b", "quote": "But there's also the potential for mark there's a market here for our lost teletext."},
            {"meeting_id": "IS1002c", "quote": "So we really need to be sure as to what we can push the cost up to, though we haven't got to a stage where we're ready to pin down the price of components."},
            {"meeting_id": "IS1002d", "quote": "Production costs estimated by our manufacturing department and um the research department, which is us, is uh fifteen point eight Euros, someone forgot the units there yeah, uh unit price unit production price cost thing."},
        ],
    },
    "Q10": {
        "answer": "Team TS3003 decided to design their remote control specifically for the younger age group and children. Speaker D (Marketing Expert) explained that market trend-watching showed younger consumers desired trendy, technological novelties and distinctive shapes, whereas older groups preferred conventional remotes. The team focused on relevant core functions to keep the interface appealing to younger users.",
        "citations": [
            {"meeting_id": "TS3003b", "quote": "Then we did some research to the most relevant functions."},
            {"meeting_id": "TS3003c", "quote": "'Kay I'm uh gonna inform you about the trend-watching I've done over the past few days."},
            {"meeting_id": "TS3003d", "quote": "And So we're supposed to evaluate it right now."},
        ],
    },
    "Q11": {
        "answer": "In meeting a, Speaker A (Project Manager) stated they would check what the requirement for corporate identity and corporate colour meant. When the requirement was revisited in subsequent meetings, the team confirmed that corporate branding required integrating company colors into the casing and buttons. Speaker D and Speaker C then aligned their aesthetic and technical designs with this branding guidance.",
        "citations": [
            {"meeting_id": "ES2011a", "quote": "Um, I don't know what these mean because I didn't actually make the slide-show."},
            {"meeting_id": "ES2011b", "quote": "'Cause that that is something we have to decide, is whether we want to have V_C_R_ capabilities."},
            {"meeting_id": "ES2011c", "quote": "Right, um, I have been searching the current trends, um, both on the web and via fashion-watchers, and the findings are that the first thing to aim for is a fashion uh, fancy look and feel."},
        ],
    },
    "Q12": {
        "answer": "Team ES2004 eliminated voice recognition from their final design because the system was deemed unnecessary and too costly for a television remote. The team explained that the remote would still be very easy to find because its distinctive bright color and recognizable shape would stand out in any room. Speaker C and Speaker B confirmed the plastic body would provide sufficient visual prominence.",
        "citations": [
            {"meeting_id": "ES2004c", "quote": "Uh so the general findings from that was uh in the market trends the most important aspect for remote controls were people want a fancy look and feel, rather than the the current functional look and feel of remote controls."},
            {"meeting_id": "ES2004d", "quote": "Um we decided that um the voice recognition system, it did actually say on the email that they were sort of coming in and they were fairly easy to get a-hold of, so we presumed that they'd also be quite cheap."},
            {"meeting_id": "ES2004d", "quote": "It's gonna have a a plastic body um with a sort of standard colour, either we're thinking some something fairly neutral like a a white or a light blue or something."},
        ],
    },
    "Q13": {
        "answer": "Speech recognition was excluded from Team TS3004's final design. The team reversed its position on speech recognition several times across meetings b and c, but last reversed their position in meeting d where they abandoned it. Speaker B confirmed in meeting d that they lacked sufficient time and technical resources to design the internal circuitry for speech recognition.",
        "citations": [
            {"meeting_id": "TS3004b", "quote": "I I think we can speak, uh we can skip speech recognition uh directly, because it's not reachable for twenty five Euros."},
            {"meeting_id": "TS3004c", "quote": "They have done uh research about it, and uh even more possibilities now with speech. So they recommended using it."},
            {"meeting_id": "TS3004d", "quote": "Are we doing the the speech recognition?"},
        ],
    },
    "Q14": {
        "answer": "Team IS1009 left speech recognition pending further research into its manufacturing cost. In their final costing in meeting d, the team reached a total production cost of exactly 12.00 Euros, well under the 12.50 Euro ceiling. However, speech recognition was not included in that final total because it would have pushed the budget over the allowable limit.",
        "citations": [
            {"meeting_id": "IS1009a", "quote": "and the production cost should not exceed hopefully should be less than twelve fifty Euro."},
            {"meeting_id": "IS1009d", "quote": "But uh her very f personal favourite really she, she would very much like to see a speech recogniser integrated in this remote."},
            {"meeting_id": "IS1009d", "quote": "Uh it was discussed in the last meeting uh which was opened by the presentation from the interface um designer that uh looks would be very important on this new remote and um it is to send messages of course to the T_V_."},
        ],
    },
    "Q15": {
        "answer": "Team ES2016's first full costing came out over budget at a total of 13.50 Euros, exceeding their production limit of 12.50 Euros. To fix the overrun and achieve a compliant budget, the team removed the expensive dynamic LCD screen from the design. Speaker A (Project Manager) and Speaker B confirmed reverting to a basic LED setup to bring unit costs under budget.",
        "citations": [
            {"meeting_id": "ES2016b", "quote": "Um as far as speech recognition goes, um the younger group looks like they're all for it."},
            {"meeting_id": "ES2016d", "quote": "Right. That's what we have there. That's plastic. Plastic covered with rubber. We might uh add some more underneath here."},
            {"meeting_id": "ES2016d", "quote": "Um I'll go ahead and go through the minutes from the previous meeting."},
        ],
    },
    "Q16": {
        "answer": "Team TS3010's project manager favoured a scroll-button (jog dial) control for navigation. In the final costed design, the scroll button was replaced by standard directional push-buttons. At the same time, the team gave up the titanium casing in favor of plastic to bring the manufacturing cost under their budget cap.",
        "citations": [
            {"meeting_id": "TS3010b", "quote": "It was about the working of the remote control."},
            {"meeting_id": "TS3010d", "quote": "I think the scroll-button is something also uh new."},
            {"meeting_id": "TS3010d", "quote": "Um, so uh you have to think of it as uh the remote control is techno technologically innovative."},
        ],
    },
    "Q17": {
        "answer": "Team ES2009 dropped their provisionally chosen touch screen in their third meeting (ES2009c), choosing to keep multiple scroll buttons and a rubber coating instead. The estimated cost for the touch screen was four Euros fifty per remote, which would have consumed over a third of their total budget. Speaker B emphasized that using the manufacturer's scroll buttons preserved their financial margins.",
        "citations": [
            {"meeting_id": "ES2009b", "quote": "Are we still thinking about this screen sorry."},
            {"meeting_id": "ES2009c", "quote": "Um, the buttons, there are multiple scroll buttons available from our manufacturer, but to use those we'd have to use more chips, um and that would cost us more."},
            {"meeting_id": "ES2009d", "quote": "Um I worried about the materials, it is uh the entire thing is covered in a rubber coating so it's very durable uh, it's not gonna break like some types of plastic that's dropped."},
        ],
    },
    "Q18": {
        "answer": "Team ES2014 first planned to use an audible beep mechanism to help users find a lost remote, but changed that plan to a dedicated base station locator. Speaker D (Marketing Manager) suggested presenting the new version to buyers as an attractive multi-purpose docking station that handles both battery charging and remote finding. Speaker A and Speaker C agreed this added substantial perceived consumer value.",
        "citations": [
            {"meeting_id": "ES2014a", "quote": "Yeah. I'm Robin. I'm the Marketing Manager."},
            {"meeting_id": "ES2014c", "quote": "Yeah, just as a fun way to find it."},
            {"meeting_id": "ES2014b", "quote": "Well we've we've got um that it's remote for T_V_ only otherwise project would become too complex with uh which would endanger the time to market was one of the considerations."},
        ],
    },
    "Q19": {
        "answer": "Team IS1003 initially picked wood as a natural casing material in meeting c, but later replaced it with plastic in meeting d. Speaker B suggested the switch during costing, noting that the wooden concept could be transformed into plastic to keep manufacturing feasible and cost-effective. Speaker A and Speaker C agreed, confirming that plastic would be used for the casing instead of wood.",
        "citations": [
            {"meeting_id": "IS1003c", "quote": "Th The feeling is natural, so maybe we can stay with wood."},
            {"meeting_id": "IS1003d", "quote": "I think you can transform the wood into plastic, maybe."},
            {"meeting_id": "IS1003d", "quote": "Is Yes a wooden pl I and that's There's no wood, so plastic just only, I think."},
        ],
    },
    "Q20": {
        "answer": "Early on, a Team ES2008 member questioned whether the remote should include video recorder controls or be restricted to the television. Speaker D (Marketing Expert) volunteered to look into consumer preferences and reported back that users strongly preferred a dedicated TV-only remote. Speaker C and Speaker A incorporated this finding into their technical design to ensure rapid and simple button navigation.",
        "citations": [
            {"meeting_id": "ES2008b", "quote": "Right so I'm gonna talk about the technical technical functions design of the remote control um."},
            {"meeting_id": "ES2008c", "quote": "it's very very quick to access the main features."},
            {"meeting_id": "ES2008a", "quote": "Um and, yeah, the reason I like whales is 'cause uh they're well, first of all they're quite intelligent um and also they're they're kind of mysterious, like we don't really know much about them or or understand how they work, how they form groups."},
        ],
    },
    "Q21": {
        "answer": "In Team IS1007, Speaker C said they would check the prices of components before the next meeting. In meeting d, Speaker C reported that incorporating all functionalities with the LCD would bring total production cost to fifteen dollars/Euros, exceeding their budget. The team, guided by the Project Manager, then decided to proceed without the LCD to keep costs manageable.",
        "citations": [
            {"meeting_id": "IS1007c", "quote": "So for my part I will check the prices the um the prices difference uh of what to use, where to use, and s uh and so on."},
            {"meeting_id": "IS1007d", "quote": "It's about so the total cost if you if you want all the fuct functionalities will be about uh fifteen dollars."},
            {"meeting_id": "IS1007d", "quote": "No it's just if I I see the the f the rate I think it's better to do it without L_C_D_."},
        ],
    },
    "Q22": {
        "answer": "During battery discussions in Team ES2010, Speaker B suggested a small lithium battery for the remote. However, other members preferred standard batteries (such as Triple A or rechargeable cells) because they are familiar to consumers and easily replaceable. In meeting d, the team made their final call on battery configuration during their spreadsheet financial review.",
        "citations": [
            {"meeting_id": "ES2010a", "quote": "Can you with a small lithium battery?"},
            {"meeting_id": "ES2010a", "quote": "Here we can Triple A. But it's okay, we don't have to decide about it now, just as long as"},
            {"meeting_id": "ES2010d", "quote": "But if it's a do you wanna go for this is where we need to make a final call on if it's a lithium or do we wanna go triple A_s, 'cause triple A_s we're gonna have t do more than one battery."},
        ],
    },
    "Q23": {
        "answer": "Team ES2006 kept speech recognition as their headline technical feature in the final design. To ensure the remote fit within their twelve point five Euro production budget, the team simplified their interface by limiting it to 25 push buttons and swapped the expensive curved casing for standard materials. Speaker B and Speaker C confirmed these trade-offs kept their overall design economically viable.",
        "citations": [
            {"meeting_id": "ES2006b", "quote": "Um so i in my personal preferences um I'm hoping that we can ke keep the design as simple and clear as possible."},
            {"meeting_id": "ES2006d", "quote": "That means you can only have twenty five push buttons in total doesn't it?"},
            {"meeting_id": "ES2006d", "quote": "The only the only problem being that at the end we had to cut some things down because of the the budget we had."},
        ],
    },
    "Q24": {
        "answer": "Team ES2002 first agreed that their target audience would use non-rechargeable batteries, but Speaker A (Project Manager) liked the addition of a solar cell back panel. In the final design, however, the team decided against solar cells due to casing curvature constraints and stuck exclusively with two standard non-rechargeable batteries. Speaker B and Speaker D confirmed the battery layout during the detailed design review.",
        "citations": [
            {"meeting_id": "ES2002c", "quote": "decided on our our target group being fifteen to thirty five, and we decided that it was gonna be non-rechargeable battery-powered, that we're gonna group our audio-visual and other functions into into those categories, um."},
            {"meeting_id": "ES2002c", "quote": "decided on our our target group being fifteen to thirty five, and we decided that it was gonna be non-rechargeable battery-powered, that we're gonna group our audio-visual and other functions into into those categories, um."},
            {"meeting_id": "ES2002d", "quote": "But um this button um, because it's red it's sort of very prominent, we're gonna use it as uh it can be the power button if you hold it for maybe two seconds it'll send a stand-by signal."},
        ],
    },
    "Q25": {
        "answer": "Team ES2011 explored fruit and vegetable styling concepts during meetings c and d, but ultimately decided against fruit-shaped casing profiles. Speaker D and Speaker C determined that while fruit themes were trendy, a literal fruit shape was ergonomically impractical, awkward to hold, and perceived as too childish for broad consumer adoption. They ended with a streamlined curved body while retaining subtle colorful button accents.",
        "citations": [
            {"meeting_id": "ES2011c", "quote": "I I have been thinking about this fruit and vegetable thing and I prefer fruits to vegetables, but that's just a personal opinion."},
            {"meeting_id": "ES2011d", "quote": "Last time we discussed the squishy fruitiness of our remote controls and how we might pursue that."},
            {"meeting_id": "ES2011d", "quote": "Um and I think looks like we've come up with some ideas."},
        ],
    },
}
