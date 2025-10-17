### Table of Contents
- Introduction
  - How does it work?
  - How long may this take to function?
  - What to expect?
  - Who is it intended for?
- I: DocsToSheet (Retreiving zoom links from google docs)
- II: ZoomDownloader

<!-- ———————————————————————————————— Introduction ———————————————————————————————— -->

### DISCLAIMER: THIS PROJECT WAS HEAVILY DEVELOPED WITH THE USE OF AI (Copilot)
# Introduction:
Zoom Scraping was a projected develop with the intention to retrieve zoom recordings from google docs and parsing all links to be downloadable mp4/m4a files. As there can be many zoom recordings that may need of its videos to be downloaded and you might not be the owner of the video uploaded, it'll help allow you to automate the process of downloading any downloadable files from any zoom recordings. This project involves a two step process and the first one can be skipped if the zoom links are already obtained.

If you run to any problems or have any questions, feel free to email me at ttiet777@gmail.com.


### Some questions you may have answered here
> How does it work?

The program is designed to take any zoom links that redirects to a zoom recording, and automatically downloads any files that the recording is able to provide. In a zoom recording on the top right, it may prompt an option to download the recordings .mp4 (video), .m4a (audio only), or .vtt (transcript). Normally, a user would have to visit the recording link, and click on the download button. But with the help of SeleniumLibrary, it allows the program to act as the user itself, and follow the same steps as a person would, but automated. This program will organize all downloaded files to its respective folder managed by the user, a visual example shown is below.

![alt text](https://media.discordapp.net/attachments/735378945440219202/1428604055785312257/Diagram.png?ex=68f31ab5&is=68f1c935&hm=8aa6d863c4a25836d335f7932eeb3e0b268d10d4e595640ab413c14c96c25f13&=&format=webp&quality=lossless&width=590&height=591)

As of the current moment, the program does not have a single download folder and requires document titles to function. A solution to this, if wished, is included in "I: DocsToSheet" below step 14.

> How long may this take to function?

Expected time if following the two step instructions (DocsToSheet & ZoomDownloader) would be 30 minutes minimum. Each recordings being parsed will take at least 40 seconds per link. As such, the estimated time for the overall download process follows this formula

	40 * (Number of Links) = Minimum of the total time

> What to expect?

After running the program, it'll be able to download all files from each zoom recordings and output the files to a designated file PATH. It'll create a subfolder of each document titles and saves each zoom recording files from whichever document it was founded in. A few things to note as well...

- You can modify which files to exclude (such as .m4a and .vtt)
- You may run this program headless if wishing to see how the program function
- When it downloads a file, it 

> Who is this intended for?

If you're someone who needs to download the files attached to the many zoom recordings you may have, this is for you! This is especially important for those who records many of their lectures on zoom but haven't locally saved their recordings already, such as online professors.

<!-- ———————————————————————————————— I: DocsToSheet ———————————————————————————————— -->

## I: DocsToSheet (Retreiving zoom links from google docs)
>This step allows you to retrieve all zoom links from google doc links, outputting the links to a google sheet for you to copy and paste into a .txt file. **If you already have the zoom links you wish to parse, you may skip this step.**

1. Go to [Google App Scripts](https://script.google.com/home), and log in
2. Create a new project on the top left
3. In "Code.gs" (the script you'll already be on), paste the code found in the **"(Google Apps Script Code) DocsToSheet.txt"**  file. It'll be located in the same ZoomScraping folder
4. On Line 3 of the variable **"sheetName"**, you may change its name to whichever you may like to call it.

		(Ex.) const sheetName = "Docs to Zoom Links";

#### Now that the script is ready, we need to give the script the links needed to parse. It'll be using a .txt file and will be uploaded uploaded to your google drive temporarily
> **Before continuing, ensure all google docs wanting to be parsed can be publicably viewed!**

5. Create a .txt file and paste all of your google docs you wish for the script to parse. The .txt may look like this, with each link having its own line. 

		https://docs.google.com/document/d/(1)/edit?usp=sharing
		https://docs.google.com/document/d/(2)/edit?usp=sharing
		https://docs.google.com/document/d/(3)/edit?usp=sharing
		https://docs.google.com/document/d/(4)/edit?usp=sharing

6. Upload the .txt to your google drive
7. Once done, change the sharability to public and copy the link
8. Returning back to the script, on line 2, change the initialization of publicDriveLink with the copied link.

#### Not all zoom recordings will have the same domain name and thus, it is important to find all domain names that needs to be retreived.
9. Check your google docs and find a few hyperlinks that redirects to a zoom recording. Take note of all the different domain names that leads to a zoom recording.
> No need to worry if you don't find all unique domain names. All links that were not included will also be included in the sheets and can be searched through if needed.
10. When you believe you found all the domain names that redirects to a zoom recording, return back to the script.
11. On Line 126, replace the value of the include function to the domain name you found. If there are more than one, add '||' and add another "link.include('domain name')".

		(Ex.) 	return link.includes('zoom1.com');
				return link.includes('zoom1.com') || link.includes('zoom2.com');

### From this point, you may save the code (ctrl+s) and press run. You may be prompted to give the script permission to access your google sheets and google drive.

> Should the script throw errors, ensure all google docs and the .txt file are publically accessible.

12.  When finished, the console will output a link to the newly created google sheet. In this, the first two column will contain the links of all found zoom links and from which doc it was located.
13.  If you wish to double check and ensure you didn't miss any other zoom links, on the right side of the two columns will also have links that did not include the domain name. You can search through and double check if are any links that may also be a zoom link.

> If you do find any excluded zoom link, feel free to add it back to the first two column, or add its domain name to the script (step 11) and rerun the program again with a different sheet name (step 4).

14.  If satisfied, copy all document title and zoom links together. An example is shown below of how it should look like
	![alt text](https://media.discordapp.net/attachments/735378945440219202/1428604055323676682/Screenshot_2025-10-12_004657.png?ex=68f31ab4&is=68f1c934&hm=5afe562b37e9f690503631c274d51afea77ef40ab961b626c22498a4f52edff2&=&format=webp&quality=lossless&width=546&height=508)

> If you wish to download all files into one document, rename everything below "Document Title" to a same name.

1.  Back in the ZoomScraping folder, in subfolder "ZoomDownloader", replace the entire text found in "zoom_links.txt" with the copied text from the google sheets. The .txt already has an example of how the formating should look like. If done correctly, the order should remain the same.
2.  From this point, we can move on part II of the program and download all zoom recordings.

<!-- ———————————————————————————————— II: ZoomDownloader ———————————————————————————————— -->

## II: ZoomDownloader

> From this point, we'll start downloading all files from zoom recordings

1. Install [latest Python version](https://www.python.org/downloads/windows/)
2. After running the installation file, ensure to checkmark "Add python.exe to PATH" before installing
3. Open Windows Terminal
4. Run this command

		pip install selenium webdriver-manager requests

5. Change the designation to the PATH of the ZoomDownloader folder. As such, an example would be
   
   		cd "C:\Users\Name\Downloads\ZoomScraping\ZoomDownloader"

6. In the "zoom_downloader.py" file, you'll need to change the PATH of where the files will be downloaded to. On line 26, change "(PATH)" to the path you like to have it be downloaded to. An example would look like

		BASE_OUTPUT_PATH = r'C:\Users\Name\Downloads\Results'

7. (Optional) You can modify which files should be excluded when downloading. On line 23 of "zoom_downloader.py", you can initiize the "REMOVE_EXTENSIONS" with any file extensions you wish to be excluded. There are comments that'll show examples if needed.

8. When ready to parse all zoom links, run this command

		python zoom_downloader.py

9.  From this point, the program should work as intended and may take a while before finishing downloading files. You should be able to find the outputted results to the PATH you set on step 6.

> Console will output all errors related to downloading a file and will also show any links that had trouble doing so.
